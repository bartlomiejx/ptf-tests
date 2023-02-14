#! @PYTHON3@
#
# Copyright(c) 2021 Intel Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
ovs-p4ctl utility allows to control P4 bridges.
"""

import argparse
import codecs
import sys
import grpc
import logging
import math
import ovspy.client
import queue
import random
import re
import socket
import struct
import threading
import time
from functools import wraps

import google.protobuf.text_format
from google.rpc import status_pb2, code_pb2

from p4.v1 import p4runtime_pb2
from p4.v1 import p4runtime_pb2_grpc
from p4.config.v1 import p4info_pb2

# context = Context()
ovs = None

USAGE = (
    "ovs-p4ctl: P4Runtime switch management utility\n"
    "usage: ovs-p4ctl [OPTIONS] COMMAND [ARG...]\n"
    "\nFor P4Runtime switches:\n"
    "  show SWITCH                         show P4Runtime switch "
    "information\n"
    "  set-pipe SWITCH PROGRAM P4INFO      set P4 pipeline for the "
    "swtich\n"
    "  get-pipe SWITCH                     print raw P4Info "
    "representation of P4 "
    "program\n"
    "  add-entry SWITCH TABLE FLOW         adds new table entry\n"
    "  modify-entry SWITCH TABLE FLOW      modify table entry\n"
    "  del-entry SWITCH TABLE KEY          delete a table entry with KEY"
    " from TABLE\n"
    "  dump-entries SWITCH [TBL]           print table entries\n"
    "  set-default-entry SWITCH TBL ACTION sets a default table entry "
    "for TBL\n"
    "  get-default-entry SWITCH TBL print  default table entry for TBL\n"
    "  add-action-profile-member SWITCH ACTION_PROFILE FLOW adds member reference\n"
    "  delete-action-profile-member SWITCH ACTION_PROFILE FLOW delete member\n"
    "  add-action-profile-group SWITCH ACTION_PROFILE FLOW adds group reference\n"
    "  delete-action-profile-group SWITCH ACTION_PROFILE FLOW delete group\n"
    "  get-action-profile-member SWITCH ACTION_PROFILE FLOW print member entries\n"
    "  get-action-profile-group SWITCH ACTION_PROFILE FLOW print group entries\n"
)


def usage():
    print(USAGE)
    sys.exit(0)


class P4RuntimeErrorFormatException(Exception):
    def __init__(self, message):
        super().__init__(message)


# Used to iterate over the p4.Error messages in a gRPC error Status object
class P4RuntimeErrorIterator:
    def __init__(self, grpc_error):
        assert grpc_error.code() == grpc.StatusCode.UNKNOWN
        self.grpc_error = grpc_error

        error = None
        # The gRPC Python package does not have a convenient way to access the
        # binary details for the error: they are treated as trailing metadata.
        for meta in self.grpc_error.trailing_metadata():
            if meta[0] == "grpc-status-details-bin":
                error = status_pb2.Status()
                error.ParseFromString(meta[1])
                break
        if error is None:
            raise P4RuntimeErrorFormatException("No binary details field")

        if len(error.details) == 0:
            raise P4RuntimeErrorFormatException(
                "Binary details field has empty Any details repeated field"
            )
        self.errors = error.details
        self.idx = 0

    def __iter__(self):
        return self

    def __next__(self):
        while self.idx < len(self.errors):
            p4_error = p4runtime_pb2.Error()
            one_error_any = self.errors[self.idx]
            if not one_error_any.Unpack(p4_error):
                raise P4RuntimeErrorFormatException(
                    "Cannot convert Any message to p4.Error"
                )
            if p4_error.canonical_code == code_pb2.OK:
                continue
            v = self.idx, p4_error
            self.idx += 1
            return v
        raise StopIteration


class P4RuntimeWriteException(Exception):
    def __init__(self, grpc_error):
        assert grpc_error.code() == grpc.StatusCode.UNKNOWN
        super().__init__()
        self.errors = []
        try:
            error_iterator = P4RuntimeErrorIterator(grpc_error)
            for error_tuple in error_iterator:
                self.errors.append(error_tuple)
        except P4RuntimeErrorFormatException:
            raise  # just propagate exception for now

    def __str__(self):
        message = "Error(s) during Write:\n"
        for idx, p4_error in self.errors:
            code_name = code_pb2._CODE.values_by_number[p4_error.canonical_code].name
            message += "\t* At index {}: {}, '{}'\n".format(
                idx, code_name, p4_error.message
            )
        return message


class P4RuntimeException(Exception):
    def __init__(self, grpc_error):
        super().__init__()
        self.grpc_error = grpc_error

    def __str__(self):
        message = "P4Runtime RPC error ({}): {}".format(
            self.grpc_error.code().name, self.grpc_error.details()
        )
        return message


def parse_p4runtime_write_error(f):
    @wraps(f)
    def handle(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.UNKNOWN:
                raise e
            raise P4RuntimeWriteException(e) from None

    return handle


def parse_p4runtime_error(f):
    @wraps(f)
    def handle(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except grpc.RpcError as e:
            raise P4RuntimeException(e) from None

    return handle


mac_pattern = re.compile("^([\da-fA-F]{2}:){5}([\da-fA-F]{2})$")


def matchesMac(mac_addr_string):
    return mac_pattern.match(mac_addr_string) is not None


def encodeMac(mac_addr_string):
    str = mac_addr_string.replace(":", "")
    return codecs.decode(str, "hex_codec")


def decodeMac(encoded_mac_addr):
    return ":".join(
        codecs.encode(s, "hex_codec").decode("utf-8")
        for s in struct.unpack(str(len(encoded_mac_addr)) + "c", encoded_mac_addr)
    )


def decodeToHex(encoded_bytes):
    return "0x" + "".join(
        codecs.encode(s, "hex_codec").decode("utf-8")
        for s in struct.unpack(str(len(encoded_bytes)) + "c", encoded_bytes)
    )


ip_pattern = re.compile("^(\d{1,3}\.){3}(\d{1,3})$")


def matchesIPv4(ip_addr_string):
    return ip_pattern.match(ip_addr_string) is not None


def encodeIPv4(ip_addr_string):
    return socket.inet_aton(ip_addr_string)


def encodeIPv4_base10(ip_addr_string):
    packedIP = socket.inet_aton(ip_addr_string)
    return struct.unpack("!L", packedIP)[0]


def decodeIPv4(encoded_ip_addr):
    return socket.inet_ntoa(encoded_ip_addr)


def bitwidthToBytes(bitwidth):
    return int(math.ceil(bitwidth / 8.0))


def encodeNum(number, bitwidth):
    byte_len = bitwidthToBytes(bitwidth)
    num_str = "%x" % number
    if number >= 2**bitwidth:
        raise Exception("Number, %d, does not fit in %d bits" % (number, bitwidth))
    val = "0" * (byte_len * 2 - len(num_str)) + num_str
    return codecs.decode(val, "hex_codec")


def decodeNum(encoded_number):
    return int(codecs.encode(encoded_number, "hex_codec"), 16)


def encode(x, bitwidth):
    "Tries to infer the type of `x` and encode it"
    byte_len = bitwidthToBytes(bitwidth)
    if (type(x) == list or type(x) == tuple) and len(x) == 1:
        x = x[0]
    encoded_bytes = None
    if type(x) == str:
        if matchesMac(x):
            encoded_bytes = encodeMac(x)
        elif matchesIPv4(x):
            encoded_bytes = encodeIPv4(x)
        elif str.isdigit(x):
            encoded_bytes = encodeNum(int(x), bitwidth)
        else:
            # Assume that the string is already encoded
            encoded_bytes = x
    elif type(x) == int:
        encoded_bytes = encodeNum(x, bitwidth)
    else:
        raise Exception("Encoding objects of %r is not supported" % type(x))
    assert len(encoded_bytes) == byte_len
    return encoded_bytes


class P4InfoHelper(object):
    def __init__(self, p4info):
        self.p4info = p4info

    def get(self, entity_type, name=None, id=None):
        if name is not None and id is not None:
            raise AssertionError("name or id must be None")

        for o in getattr(self.p4info, entity_type):
            pre = o.preamble
            if name:
                if pre.name == name or pre.alias == name:
                    return o
            else:
                if pre.id == id:
                    return o

        if name:
            raise AttributeError("Could not find %r of type %s" % (name, entity_type))
        else:
            raise AttributeError("Could not find id %r of type %s" % (id, entity_type))

    def get_id(self, entity_type, name):
        return self.get(entity_type, name=name).preamble.id

    def implementation_id(self, entity_type, name):
        return self.get(entity_type, name=name).implementation_id

    def get_name(self, entity_type, id):
        return self.get(entity_type, id=id).preamble.name

    def get_alias(self, entity_type, id):
        return self.get(entity_type, id=id).preamble.alias

    def __getattr__(self, attr):
        # Synthesize convenience functions for name to id lookups for top-level
        # entities
        # e.g. get_tables_id(name_string) or get_actions_id(name_string)
        m = re.search("^get_(\w+)_id$", attr)
        if m:
            primitive = m.group(1)
            return lambda name: self.get_id(primitive, name)

        # Synthesize convenience functions for id to name lookups
        # e.g. get_tables_name(id) or get_actions_name(id)
        m = re.search("^get_(\w+)_name$", attr)
        if m:
            primitive = m.group(1)
            return lambda id: self.get_name(primitive, id)

        raise AttributeError("%r object has no attribute %r" % (self.__class__, attr))

    def get_match_fields(self, table_name):
        for t in self.p4info.tables:
            pre = t.preamble
            if pre.name == table_name:
                return t.match_fields

    def get_match_field(self, table_name, name=None, id=None):
        for t in self.p4info.tables:
            pre = t.preamble
            if pre.name == table_name:
                for mf in t.match_fields:
                    if name is not None:
                        if mf.name == name:
                            return mf
                    elif id is not None:
                        if mf.id == id:
                            return mf
        raise AttributeError(
            "%r has no attribute %r" % (table_name, name if name is not None else id)
        )

    def get_match_field_id(self, table_name, match_field_name):
        return self.get_match_field(table_name, name=match_field_name).id

    def get_match_field_name(self, table_name, match_field_id):
        return self.get_match_field(table_name, id=match_field_id).name

    def get_match_field_width(self, table_name, match_field_name):
        return self.get_match_field(table_name, name=match_field_name).bitwidth

    def get_match_field_pb(self, table_name, match_field_name, value):
        p4info_match = self.get_match_field(table_name, match_field_name)
        bitwidth = p4info_match.bitwidth
        p4runtime_match = p4runtime_pb2.FieldMatch()
        p4runtime_match.field_id = p4info_match.id
        match_type = p4info_match.match_type
        if match_type == p4info_pb2.MatchField.EXACT:
            exact = p4runtime_match.exact
            exact.value = encode(value, bitwidth)
        elif match_type == p4info_pb2.MatchField.LPM:
            lpm = p4runtime_match.lpm
            lpm.value = encode(value[0], bitwidth)
            lpm.prefix_len = value[1]
        elif match_type == p4info_pb2.MatchField.TERNARY:
            lpm = p4runtime_match.ternary
            lpm.value = encode(value[0], bitwidth)
            lpm.mask = encode(value[1], bitwidth)
        elif match_type == p4info_pb2.MatchField.RANGE:
            lpm = p4runtime_match.range
            lpm.low = encode(value[0], bitwidth)
            lpm.high = encode(value[1], bitwidth)
        else:
            raise Exception("Unsupported match type with type %r" % match_type)
        return p4runtime_match

    def get_match_field_value(self, match_field):
        match_type = match_field.WhichOneof("field_match_type")
        if match_type == "valid":
            return match_field.valid.value
        elif match_type == "exact":
            return match_field.exact.value
        elif match_type == "lpm":
            return (match_field.lpm.value, match_field.lpm.prefix_len)
        elif match_type == "ternary":
            return (match_field.ternary.value, match_field.ternary.mask)
        elif match_type == "range":
            return (match_field.range.low, match_field.range.high)
        else:
            raise Exception("Unsupported match type with type %r" % match_type)

    def get_action_params(self, action_name):
        for a in self.p4info.actions:
            pre = a.preamble
            if pre.name == action_name:
                return a.params

    def get_action_param(self, action_name, name=None, id=None):
        for a in self.p4info.actions:
            pre = a.preamble
            if pre.name == action_name:
                for p in a.params:
                    if name is not None:
                        if p.name == name:
                            return p
                    elif id is not None:
                        if p.id == id:
                            return p
        raise AttributeError(
            "action %r has no param %r, (has: %r)"
            % (action_name, name if name is not None else id, a.params)
        )

    def get_action_param_id(self, action_name, param_name):
        return self.get_action_param(action_name, name=param_name).id

    def get_action_param_name(self, action_name, param_id):
        return self.get_action_param(action_name, id=param_id).name

    def get_action_param_pb(self, action_name, param_name, value):
        p4info_param = self.get_action_param(action_name, param_name)
        p4runtime_param = p4runtime_pb2.Action.Param()
        p4runtime_param.param_id = p4info_param.id
        p4runtime_param.value = encode(value, p4info_param.bitwidth)
        return p4runtime_param

    def buildTableEntry(
        self,
        table_name,
        match_fields=None,
        default_action=False,
        action_name=None,
        action_params=None,
        priority=None,
        group_id=0,
        member_id=0,
    ):
        table_entry = p4runtime_pb2.TableEntry()
        table_entry.table_id = self.get_tables_id(table_name)

        if priority is not None:
            table_entry.priority = priority

        if match_fields:
            table_entry.match.extend(
                [
                    self.get_match_field_pb(table_name, match_field_name, value)
                    for match_field_name, value in match_fields.items()
                ]
            )

        if default_action:
            table_entry.is_default_action = True

        if action_name:
            action = table_entry.action.action
            action.action_id = self.get_actions_id(action_name)
            if action_params:
                action.params.extend(
                    [
                        self.get_action_param_pb(action_name, field_name, value)
                        for field_name, value in action_params.items()
                    ]
                )

        if member_id:
            table_entry.action.action_profile_member_id = member_id

        if group_id:
            table_entry.action.action_profile_group_id = group_id

        return table_entry

    def buildActionProfileMember(
        self,
        table_name,
        member_id=0,
        action_name=None,
        action_params=None,
        priority=None,
    ):
        action_profile_member = p4runtime_pb2.ActionProfileMember()

        action_profile_member.action_profile_id = self.get_action_profiles_id(
            table_name
        )
        action_profile_member.member_id = member_id

        if action_name:
            action = action_profile_member.action
            action.action_id = self.get_actions_id(action_name)
            if action_params:
                action.params.extend(
                    [
                        self.get_action_param_pb(action_name, field_name, value)
                        for field_name, value in action_params.items()
                    ]
                )

        return action_profile_member

    def buildActionProfileGroup(self, table_name, group_id=0, max_size=0, members=[]):
        action_profile_group = p4runtime_pb2.ActionProfileGroup()
        action_profile_group.action_profile_id = self.get_action_profiles_id(table_name)
        action_profile_group.group_id = group_id
        for i in members:
            if str.isdigit(i):
                apg = action_profile_group.members.add()
                apg.member_id = int(i)

        action_profile_group.max_size = max_size
        return action_profile_group


class P4RuntimeClient:
    def __init__(self, device_id, grpc_addr="localhost:9559", election_id=(1, 0)):
        self.device_id = device_id
        self.election_id = election_id

        try:
            self.channel = grpc.insecure_channel(grpc_addr)
        except Exception as e:
            raise e
        self.stub = p4runtime_pb2_grpc.P4RuntimeStub(self.channel)
        self.set_up_stream()

    def set_up_stream(self):
        self.stream_out_q = queue.Queue()
        self.stream_in_q = queue.Queue()

        def stream_req_iterator():
            while True:
                p = self.stream_out_q.get()
                if p is None:
                    break
                yield p

        def stream_recv_wrapper(stream):
            @parse_p4runtime_error
            def stream_recv():
                for p in stream:
                    self.stream_in_q.put(p)

            try:
                stream_recv()
            except P4RuntimeException as e:
                logging.critical("StreamChannel error, closing stream")
                logging.critical(e)
                self.stream_in_q.put(None)

        self.stream = self.stub.StreamChannel(stream_req_iterator())
        self.stream_recv_thread = threading.Thread(
            target=stream_recv_wrapper, args=(self.stream,)
        )
        self.stream_recv_thread.start()

        self.handshake()

    def handshake(self):
        req = p4runtime_pb2.StreamMessageRequest()
        arbitration = req.arbitration
        arbitration.device_id = self.device_id
        election_id = arbitration.election_id
        election_id.high = self.election_id[0]
        election_id.low = self.election_id[1]
        self.stream_out_q.put(req)

        rep = self.get_stream_packet("arbitration", timeout=2)
        if rep is None:
            logging.critical("Failed to establish session with server")
            sys.exit(1)
        is_master = rep.arbitration.status.code == code_pb2.OK
        logging.debug(
            "Session established, client is '{}'".format(
                "master" if is_master else "slave"
            )
        )
        if not is_master:
            print("You are not master, you only have read access " "to the server")

    def get_stream_packet(self, type_, timeout=1):
        start = time.time()
        try:
            while True:
                remaining = timeout - (time.time() - start)
                if remaining < 0:
                    break
                msg = self.stream_in_q.get(timeout=remaining)
                if msg is None:
                    return None
                if not msg.HasField(type_):
                    continue
                return msg
        except queue.Empty:  # timeout expired
            pass
        return None

    @parse_p4runtime_error
    def get_p4info(self):
        req = p4runtime_pb2.GetForwardingPipelineConfigRequest()
        req.device_id = self.device_id
        req.response_type = (
            p4runtime_pb2.GetForwardingPipelineConfigRequest.P4INFO_AND_COOKIE
        )
        rep = self.stub.GetForwardingPipelineConfig(req)
        return rep.config.p4info

    @parse_p4runtime_error
    def set_fwd_pipe_config(self, p4info_path, bin_path):
        req = p4runtime_pb2.SetForwardingPipelineConfigRequest()
        req.device_id = self.device_id
        election_id = req.election_id
        election_id.high = self.election_id[0]
        election_id.low = self.election_id[1]
        req.action = p4runtime_pb2.SetForwardingPipelineConfigRequest.VERIFY_AND_COMMIT
        with open(p4info_path, "r") as f1:
            with open(bin_path, "rb") as f2:
                try:
                    google.protobuf.text_format.Merge(f1.read(), req.config.p4info)
                except google.protobuf.text_format.ParseError:
                    logging.error("Error when parsing P4Info")
                    raise
                req.config.p4_device_config = f2.read()
        return self.stub.SetForwardingPipelineConfig(req)

    def tear_down(self):
        if self.stream_out_q:
            self.stream_out_q.put(None)
            self.stream_recv_thread.join()
        self.channel.close()
        # avoid a race condition if channel deleted when process terminates
        del self.channel

    @parse_p4runtime_write_error
    def write(self, req):
        req.device_id = self.device_id
        election_id = req.election_id
        election_id.high = self.election_id[0]
        election_id.low = self.election_id[1]
        return self.stub.Write(req)

    @parse_p4runtime_write_error
    def write_update(self, update):
        req = p4runtime_pb2.WriteRequest()
        req.device_id = self.device_id
        election_id = req.election_id
        election_id.high = self.election_id[0]
        election_id.low = self.election_id[1]
        req.updates.extend([update])
        return self.stub.Write(req)

    def read_one(self, entity):
        req = p4runtime_pb2.ReadRequest()
        req.device_id = self.device_id
        req.entities.extend([entity])
        return self.stub.Read(req)


def resolve_device_id_by_bridge_name(bridge_name):
    global ovs
    ovs = ovspy.client.OvsClient(5000)

    if ovs.find_bridge(bridge_name) is None:
        raise Exception("bridge '{}' doesn't exist".format(bridge_name))

    for br in ovs.get_bridge_raw():
        if br["name"] == bridge_name:
            other_configs = br["other_config"][1][0]
            for i, cfg in enumerate(other_configs):
                if cfg == "device_id":
                    return int(other_configs[i + 1])
    # This function should not reach this line
    raise Exception(
        "bridge '{}' does not have " "'device_id' configured".format(bridge_name)
    )


def with_client(f):
    @wraps(f)
    def handle(*args, **kwargs):
        client = None
        try:
            # client = P4RuntimeClient(device_id=
            #           resolve_device_id_by_bridge_name(args[0]))
            client = P4RuntimeClient(device_id=1)
            f(client, *args, **kwargs)
        except Exception as e:
            raise e
        finally:
            if client:
                client.tear_down()

    return handle


interface_query = {
    "method": "transact",
    "params": [
        "Open_vSwitch",
        {
            "op": "select",
            "table": "Interface",
            "where": [],
        },
    ],
    "id": random.randint(0, 10000),
}


def ovs_get_interfaces():
    result = ovs._send(interface_query)
    return result["result"][0]["rows"]


def ovs_get_interface(id):
    for intf in ovs_get_interfaces():
        if intf["_uuid"][1] == id:
            return intf


def ovs_get_interfaces_by_bridge_name(bridge):
    interfaces = []
    br = ovs.find_bridge(bridge)

    if not br:
        return interfaces

    for p in br.get_ports():
        port = p.get_raw()
        interfaces_ids = []
        if port["interfaces"][0] == "set":
            for i in port["interfaces"][1]:
                interfaces_ids.append(i[1])
        elif port["interfaces"][0] == "uuid":
            interfaces_ids.append(port["interfaces"][1])

        for id in interfaces_ids:
            intf = ovs_get_interface(id)
            interfaces.append(intf)

    return interfaces


@with_client
def p4ctl_show(client, bridge):
    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)

    bridge_line = "P4Runtime switch {} information:\n".format(bridge)
    device_id_line = "device_id: {}\n".format(client.device_id)
    n_tables_line = "n_tables: {}\n".format(len(p4info.tables))
    tables_line = "tables:"
    for tbl in p4info.tables:
        match = [mf.name for mf in tbl.match_fields]
        actions = [helper.get_name("actions", a.id) for a in tbl.action_refs]
        tables_line += " {}(match=[{}], actions=[{}])".format(
            tbl.preamble.name, ", ".join(match), ", ".join(actions)
        )
    tables_line += "\n"

    ports = []
    for intf in ovs_get_interfaces_by_bridge_name(bridge):
        mac = intf["mac_in_use"]
        link_state = intf["link_state"].upper()
        speed = int(int(intf["link_speed"]) / 1000)
        rx_packets = intf["statistics"][1][1][1]
        rx_bytes = intf["statistics"][1][8][1]
        tx_packets = intf["statistics"][1][12][1]
        tx_bytes = intf["statistics"][1][9][1]
        port_str = (
            "  {}({}):\n\tstate: {}\n\taddr:{}\n\tspeed: "
            "{}\n\tstats: {}".format(
                intf["ofport"] if intf["name"] != bridge else "LOCAL",
                intf["name"],
                mac,
                link_state,
                "{} Mbps".format(str(speed)),
                "rx_packets={}, rx_bytes={}, tx_packets={}, tx_bytes={}".format(
                    rx_packets, rx_bytes, tx_packets, tx_bytes
                ),
            )
        )
        ports.append(port_str)

    print(
        "".join(
            [bridge_line, device_id_line, n_tables_line, tables_line, "\n".join(ports)]
        )
    )


@with_client
def p4ctl_set_pipe(client, bridge, device_config, p4info):
    client.set_fwd_pipe_config(p4info, device_config)


@with_client
def p4ctl_get_pipe(client, bridge):
    p4info = client.get_p4info()
    if p4info:
        print("P4Info of bridge {}:".format(bridge))
        print(p4info)


def parse_match_key(key):
    match_keys = dict()
    mk_fields = key.split(",")
    for mk_field in mk_fields:
        m = mk_field.split("=")
        if "/" in m[1]:
            lpm_mk = m[1].split("/")
            match_keys[m[0]] = (lpm_mk[0], int(lpm_mk[1]))
        else:
            match_keys[m[0]] = m[1]
    return match_keys


def parse_action(action):
    """
    Accepted input types for action values are
    IP - String, Hex or Decimal
    MAC - String, Hex or Decimal
    Other - Hex Or Decimal
    """
    act_fields = action.split("(")
    action_name = act_fields[0]
    if len(act_fields) > 1:
        params = act_fields[1].split(")")[0]
        act_data = params.split(",")
        act_data = [
            encodeIPv4_base10(a)
            if matchesIPv4(a)
            else (
                int.from_bytes(encodeMac(a), "big")
                if matchesMac(a)
                else (int(a, 0) if a.find("0x") != -1 else int(a))
            )
            for a in act_data
        ]
    else:
        act_data = [""]
    return action_name, act_data


def parse_flow(flow):
    tmp = flow.split(",action=")
    mk = tmp[0]
    act = tmp[1]

    match_keys = parse_match_key(mk)
    action_name, act_data = parse_action(act)
    return match_keys, action_name, act_data


def parse_flow_as(flow):
    extract_mk = flow.split(",")
    mk = extract_mk[0]
    extract_key = extract_mk[1]
    extract_act = extract_key.split("=")
    key = extract_act[0]
    act = extract_act[1]
    action_name = None
    act_data = None
    group_id = 0
    member_id = 0

    if key == "action":
        action_name, act_data = parse_action(act)
    elif key == "group_id":
        group_id = act
    elif key == "member_id":
        member_id = act

    match_keys = parse_match_key(mk)
    return match_keys, action_name, act_data, group_id, member_id


def parse_profile_mem(flow):
    extract_mem = flow.split(",member_id=")
    action_param = extract_mem[0]
    mem_id = extract_mem[1]

    act = action_param.split("action=")
    action_name, act_data = parse_action(act[1])
    return action_name, act_data, mem_id


def parse_profile_group(flow):
    extract_group = flow.split(",reference_members=")
    group_id = extract_group[0].split("group_id=")
    mem = extract_group[1].split(",max_size=")

    ref_members = mem[0]
    max_size = mem[1]
    return group_id[1], ref_members, max_size


@with_client
def p4ctl_add_entry(client, bridge, tbl_name, flow):
    """
    add-entry SWITCH TABLE MATCH_KEY ACTION ACTION_DATA
    Example:
        ovs-p4ctl add-entry br0 pipe.filter_tbl
                    headers.ipv4.dstAddr=10.10.10.10,action=pipe.push_mpls(10)
    """

    grp_id = 0
    mem_id = 0
    if flow.find("group_id") != -1 or flow.find("member_id") != -1:
        # For TableAction when we use type as action_profile_member_id or
        # action_profile_group_id, ovs-p4ctl expects either group_id or
        # member_id as part of flow. Hence delimiter as 'action=' doesnt work
        # here. Use parse_flow_as in this case, where we use ',' as a delimiter
        match_keys, action, action_data, grp_id, mem_id = parse_flow_as(flow)
    else:
        # For TableAction when we use type as Action, ovs-p4ctl expects flow to
        # have an 'action=' configured. In this parse_flow, we use 'action=' as
        # a delimiter.
        match_keys, action, action_data = parse_flow(flow)

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)

    te = helper.buildTableEntry(
        table_name=tbl_name,
        match_fields=match_keys,
        action_name=action,
        action_params=action_data
        if action_data == None
        else {
            a.name: int(action_data[idx])
            for idx, a in enumerate(helper.get_action_params(action))
        },
        priority=None,
        group_id=int(grp_id),
        member_id=int(mem_id),
    )

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.INSERT
    update.entity.table_entry.CopyFrom(te)

    client.write_update(update)


@with_client
def p4ctl_mod_entry(client, bridge, tbl_name, flow):
    """
    mod-entry SWITCH TABLE MATCH_KEY ACTION ACTION_DATA
    Example:
        ovs-p4ctl mod-entry br0 pipe.filter_tbl
                    headers.ipv4.dstAddr=10.10.10.10,action=pipe.push_mpls(10)
    """
    grp_id = 0
    mem_id = 0
    if flow.find("group_id") != -1 or flow.find("member_id") != -1:
        # For TableAction when we use type as action_profile_member_id or
        # action_profile_group_id, ovs-p4ctl expects either group_id or
        # member_id as part of flow. Hence delimiter as 'action=' doesnt work
        # here. Use parse_flow_as in this case, where we use ',' as a delimiter
        match_keys, action, action_data, grp_id, mem_id = parse_flow_as(flow)
    else:
        # For TableAction when we use type as Action, ovs-p4ctl expects flow to
        # have an 'action=' configured. In this parse_flow, we use 'action=' as
        # a delimiter.
        match_keys, action, action_data = parse_flow(flow)

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)

    te = helper.buildTableEntry(
        table_name=tbl_name,
        match_fields=match_keys,
        action_name=action,
        action_params=action_data
        if action_data == None
        else {
            a.name: int(action_data[idx])
            for idx, a in enumerate(helper.get_action_params(action))
        },
        priority=None,
        group_id=int(grp_id),
        member_id=int(mem_id),
    )

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.MODIFY
    update.entity.table_entry.CopyFrom(te)

    client.write_update(update)


@with_client
def p4ctl_set_default_entry(client, bridge, tbl_name, action):
    """
    set-default-entry SWITCH TABLE ACTION
    Example:
        ovs-p4ctl set-default-entry br0 pipe.filter_tbl pipe.push_mpls(10)
    """

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))
    helper = P4InfoHelper(p4info)

    action_name, action_data = parse_action(action)
    te = helper.buildTableEntry(
        table_name=tbl_name,
        default_action=True,
        action_name=action_name,
        action_params={
            a.name: int(action_data[idx])
            for idx, a in enumerate(helper.get_action_params(action_name))
        },
    )

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.MODIFY
    update.entity.table_entry.CopyFrom(te)

    client.write_update(update)


@with_client
def p4ctl_get_default_entry(client, bridge, tbl_name):
    """
    get-default-entry SWITCH TABLE
    Example:
        ovs-p4ctl get-default-entry br0 pipe.filter_tbl
    """
    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))
    helper = P4InfoHelper(p4info)

    entity = p4runtime_pb2.Entity()
    table_entry = entity.table_entry
    table_entry.table_id = helper.get_tables_id(tbl_name)
    table_entry.is_default_action = True

    print("Default table entry for bridge {}:".format(bridge))
    for response in client.read_one(entity):
        for entry in response.entities:
            try:
                print(_format_entry(helper, entry.table_entry))
            except AttributeError:
                print(" No default entry set!")


@with_client
def p4ctl_del_entry(client, bridge, tbl_name, match_key):
    key = parse_match_key(match_key)
    p4info = client.get_p4info()

    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)

    te = helper.buildTableEntry(
        table_name=tbl_name,
        match_fields=key,
    )

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.DELETE

    update.entity.table_entry.CopyFrom(te)

    client.write_update(update)


def _format_entry(p4info_helper, table_entry):
    tbl_name = p4info_helper.get_name("tables", table_entry.table_id)
    output_buffer = "  "
    output_buffer += "table={}".format(tbl_name)
    if table_entry.priority is not None:
        output_buffer += " priority={}".format(table_entry.priority)

    first = True
    for mf in table_entry.match:
        match_field_name = p4info_helper.get_match_field_name(tbl_name, mf.field_id)
        mf_val = p4info_helper.get_match_field_value(mf)
        if type(mf_val) == tuple:
            mf_val = "{}/{}".format(decodeToHex(mf_val[0]), mf_val[1])
        else:
            mf_val = decodeToHex(mf_val)
        if first:
            output_buffer += " {}={}".format(match_field_name, mf_val)
            first = False
        else:
            output_buffer += ",{}={}".format(match_field_name, mf_val)

    output_buffer += " actions="
    action_name = p4info_helper.get_name("actions", table_entry.action.action.action_id)
    action_params = p4info_helper.get_action_params(action_name)
    params_str = ""
    for idx, param in enumerate(table_entry.action.action.params):
        params_str += "{}={}".format(action_params[idx].name, decodeToHex(param.value))
    output_buffer += "{}({})".format(action_name, params_str)

    return output_buffer


def _format_member(p4info_helper, apm):
    apm_name = p4info_helper.get_name("action_profiles", apm.action_profile_id)
    output_buffer = "  "
    output_buffer += "action_profiles={}".format(apm_name)

    output_buffer += " actions="
    action_name = p4info_helper.get_name("actions", apm.action.action_id)
    action_params = p4info_helper.get_action_params(action_name)
    params_str = ""
    for idx, param in enumerate(apm.action.params):
        params_str += "{}={}".format(
            action_params[idx].name, int.from_bytes(param.value, "big")
        )
    output_buffer += "{}({})".format(action_name, params_str)

    return output_buffer


def _format_group(p4info_helper, apg):
    apm_name = p4info_helper.get_name("action_profiles", apg.action_profile_id)
    output_buffer = "  "
    output_buffer += "action_profiles={}".format(apm_name)

    output_buffer += " reference_members="

    converted_list = [str(member.member_id) for member in apg.members]
    params_str = ",".join(converted_list)

    output_buffer += "({})".format(params_str)

    output_buffer += " max_size=" + str(apg.max_size)

    return output_buffer


@with_client
def p4ctl_dump_entries(client, bridge, tbl_name=None):
    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))
    helper = P4InfoHelper(p4info)
    entity = p4runtime_pb2.Entity()
    table_entry = entity.table_entry

    if not tbl_name:
        table_entry.table_id = 0
    else:
        table_entry.table_id = helper.get_tables_id(tbl_name)

    print("Table entries for bridge {}:".format(bridge))
    for response in client.read_one(entity):
        for entry in response.entities:
            print(_format_entry(helper, entry.table_entry))


@with_client
def p4ctl_add_group(client, bridge, tbl_name, flow):
    """
    add-action-profile-group SWITCH TABLE GROUP_ID MEMBER_ID/ACTIONS MAX_SIZE
    Example:
        ovs-p4ctl add-action-profile-group br0 pipe.filter_tbl
                    group_id=1,reference_members=(1,2),max_size=2
    """
    group_id, members, max_size = parse_profile_group(flow)
    if int(group_id) == 0:
        print("Group ID 0 is un-supported.")
        return

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)

    apg = helper.buildActionProfileGroup(
        table_name=tbl_name,
        group_id=int(group_id),
        max_size=int(max_size),
        members=members,
    )

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.INSERT
    update.entity.action_profile_group.CopyFrom(apg)

    client.write_update(update)


@with_client
def p4ctl_mod_group(client, bridge, tbl_name, flow):
    """
    modify-action-profile-group SWITCH TABLE GROUP_ID
                                MEMBER_ID/ACTIONS MAX_SIZE
    Example:
        ovs-p4ctl modify-action-profile-group br0 pipe.filter_tbl
                   group_id=1,reference_members=(1,2),max_size=2
    """

    group_id, members, max_size = parse_profile_group(flow)
    if int(group_id) == 0:
        print("Group ID 0 is un-supported.")
        return

    print(
        "Currently modify group functionality is un-supported by backend " "target.!!!"
    )
    print(
        "Instead delete group:",
        group_id,
        "and re-add same group with " "members:",
        members,
        " size:",
        max_size,
    )
    return

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)

    apg = helper.buildActionProfileGroup(
        table_name=tbl_name,
        group_id=int(group_id),
        max_size=int(max_size),
        members=members,
    )

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.MODIFY
    update.entity.action_profile_group.CopyFrom(apg)

    client.write_update(update)


@with_client
def p4ctl_del_group(client, bridge, tbl_name, flow):
    """
    delete-action-profile-group SWITCH TABLE GROUP_ID
    Example:
        ovs-p4ctl delete-action-profile-group br0 pipe.filter_tbl
                  group_id=1
    """
    group_id = flow.split("group_id=")[1]
    if int(group_id) == 0:
        print("Group ID 0 is un-supported.")
        return

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)
    apg = helper.buildActionProfileGroup(table_name=tbl_name, group_id=int(group_id))

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.DELETE
    update.entity.action_profile_group.CopyFrom(apg)

    client.write_update(update)


@with_client
def p4ctl_add_member(client, bridge, tbl_name, flow):
    """
    add-action-profile-member SWITCH TABLE ACTION ACTION_DATA MEMBER_ID
    Example:
        ovs-p4ctl add-action-profile-member br0 pipe.filter_tbl
                    action=pipe.push_mpls(10),member_id=1
    """
    action, action_data, mem_id = parse_profile_mem(flow)
    if int(mem_id) == 0:
        print("Member ID 0 is un-supported.")
        return

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)

    apm = helper.buildActionProfileMember(
        table_name=tbl_name,
        member_id=int(mem_id),
        action_name=action,
        action_params={
            a.name: int(action_data[idx])
            for idx, a in enumerate(helper.get_action_params(action))
        },
    )

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.INSERT
    update.entity.action_profile_member.CopyFrom(apm)

    client.write_update(update)


@with_client
def p4ctl_del_member(client, bridge, tbl_name, flow):
    """
    delete-action-profile-member SWITCH TABLE MEMBER_ID
    Example:
        ovs-p4ctl delete-action-profile-member br0 pipe.filter_tbl
                  member_id=1
    """
    member_id = flow.split("member_id=")[1]

    if int(member_id) == 0:
        print("Member ID 0 is un-supported.")
        return

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)
    apm = helper.buildActionProfileMember(table_name=tbl_name, member_id=int(member_id))

    update = p4runtime_pb2.Update()
    update.type = p4runtime_pb2.Update.DELETE
    update.entity.action_profile_member.CopyFrom(apm)

    client.write_update(update)


@with_client
def p4ctl_get_member(client, bridge, tbl_name, flow):
    """
    get-action-profile-member SWITCH TABLE MEMBER_ID
    Example:
        ovs-p4ctl get-action-profile-member br0 pipe.filter_tbl
                    "member_id=1"
    """

    member_id = flow.split("member_id=")[1]
    if int(member_id) == 0:
        print("Member ID 0 is un-supported.")
        return

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)
    entity = p4runtime_pb2.Entity()
    apm = entity.action_profile_member

    apm.member_id = int(member_id)
    if not tbl_name:
        apm.action_profile_id = 0
    else:
        apm.action_profile_id = helper.get_action_profiles_id(tbl_name)

    print("Action associated with member_id: ", member_id)
    for response in client.read_one(entity):
        for entry in response.entities:
            print(_format_member(helper, entry.action_profile_member))


@with_client
def p4ctl_get_group(client, bridge, tbl_name, flow):
    """
    get-action-profile-group SWITCH TABLE GROUP_ID
    Example:
        ovs-p4ctl get-action-profile-group br0 pipe.filter_tbl
                    "group_id=1"
    """
    group_id = flow.split("group_id=")[1]
    if int(group_id) == 0:
        print("Group ID 0 is un-supported.")
        return

    p4info = client.get_p4info()
    if not p4info:
        raise Exception("cannot retrieve P4Info from device {}".format(bridge))

    helper = P4InfoHelper(p4info)
    entity = p4runtime_pb2.Entity()
    apg = entity.action_profile_group

    apg.group_id = int(group_id)
    if not tbl_name:
        apg.action_profile_id = 0
    else:
        apg.action_profile_id = helper.get_action_profiles_id(tbl_name)

    print("Members associated with group: ", group_id)
    for response in client.read_one(entity):
        for entry in response.entities:
            print(_format_group(helper, entry.action_profile_group))


all_commands = {
    "show": (p4ctl_show, 1),
    "set-pipe": (p4ctl_set_pipe, 3),
    "get-pipe": (p4ctl_get_pipe, 1),
    "add-entry": (p4ctl_add_entry, 3),
    "modify-entry": (p4ctl_mod_entry, 3),
    "set-default-entry": (p4ctl_set_default_entry, 3),
    "get-default-entry": (p4ctl_get_default_entry, 2),
    "del-entry": (p4ctl_del_entry, 2),
    "dump-entries": (p4ctl_dump_entries, 1),
    "add-action-profile-member": (p4ctl_add_member, 3),
    "delete-action-profile-member": (p4ctl_del_member, 3),
    "add-action-profile-group": (p4ctl_add_group, 3),
    # "modify-action-profile-group": (p4ctl_mod_group, 3),
    "delete-action-profile-group": (p4ctl_del_group, 3),
    "get-action-profile-member": (p4ctl_get_member, 3),
    "get-action-profile-group": (p4ctl_get_group, 3),
}


def validate_args(argv, command, expected_nr):
    if len(argv) - 2 < expected_nr:
        raise Exception(
            "ovs-p4ctl: '{}' command requires at least {} "
            "arguments".format(command, expected_nr)
        )


def main():
    if len(sys.argv) < 2:
        print("ovs-p4ctl: missing command name; use --help for help")
        sys.exit(1)
    parser = argparse.ArgumentParser(usage=USAGE)
    parser.add_argument("command", help="Subcommand to run")

    args = parser.parse_args(sys.argv[1:2])
    if args.command not in all_commands.keys():
        usage()

    try:
        # use dispatch pattern to invoke method with same name
        # but first validate number of arguments
        validate_args(
            sys.argv, command=args.command, expected_nr=all_commands[args.command][1]
        )
        all_commands[args.command][0](*sys.argv[2:])
    except Exception as e:
        print("Error:", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
