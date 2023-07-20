# Copyright (C) 2022 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
from system_tools.terminals import SSHTerminal

target = "kvm"
from system_tools.config import TestConfig, import_base_test, IPUStorageConfig
from system_tools.const import FIO_COMMON, FIO_IO_PATTERNS
from system_tools.errors import CommandException
from system_tools.test_platform import PlatformFactory

BaseTest = import_base_test(target)


# class TestKVMMinHotPlugAndFio(BaseTest):
#     def setUp(self):
#         self.tests_config = TestConfig()
#         self.platforms_factory = PlatformFactory(self.tests_config.cmd_sender_platform)
#         self.storage_target_platform = (
#             self.platforms_factory.create_storage_target_platform()
#         )
#         self.ipu_storage_platform = self.platforms_factory.create_ipu_storage_platform()
#         self.host_target_platform = self.platforms_factory.create_host_target_platform()
#
#     def runTest(self):
#         self.assertTrue(
#             self.storage_target_platform.is_port_free(self.tests_config.nvme_port)
#         )
#         self.storage_target_platform.create_subsystem(
#             self.tests_config.nqn,
#             self.tests_config.nvme_port,
#             self.tests_config.spdk_port,
#         )
#         self.assertFalse(
#             self.storage_target_platform.is_port_free(self.tests_config.nvme_port)
#         )
#         self.assertTrue(
#             self.storage_target_platform.is_app_listening_on_port(
#                 "spdk_tgt", self.tests_config.nvme_port
#             )
#         )
#
#         remote_nvme_storages = self.storage_target_platform.create_ramdrives(
#             self.tests_config.min_ramdrive,
#             self.tests_config.nvme_port,
#             self.tests_config.nqn,
#             self.tests_config.spdk_port,
#         )
#         self.assertEqual(len(remote_nvme_storages), self.tests_config.min_ramdrive)
#
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(), 0
#         )
#         devices_handles = (
#             self.ipu_storage_platform.create_virtio_blk_devices_sequentially(
#                 self.host_target_platform.get_service_address(),
#                 remote_nvme_storages,
#             )
#         )
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(),
#             self.tests_config.min_ramdrive,
#         )
#
#         for io_pattern in FIO_IO_PATTERNS:
#             fio_args = {
#                 **FIO_COMMON,
#                 "rw": io_pattern.lower(),
#             }
#             for device in devices_handles:
#                 self.assertTrue(device.run_fio(fio_args))
#
#         self.ipu_storage_platform.delete_virtio_blk_devices(devices_handles)
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(), 0
#         )
#
#         second_delete_responses = self.ipu_storage_platform.delete_virtio_blk_devices(
#             devices_handles
#         )
#         for response in second_delete_responses:
#             self.assertTrue(response)
#
#     def tearDown(self):
#         self.platforms_factory.cmd_sender.stop()
#         self.ipu_storage_platform.clean()
#         self.storage_target_platform.clean()
#         self.host_target_platform.clean()
#
#
# class TestKVMMaxHotPlug(BaseTest):
#     def setUp(self):
#         self.tests_config = TestConfig()
#         self.platforms_factory = PlatformFactory(self.tests_config.cmd_sender_platform)
#         self.storage_target_platform = (
#             self.platforms_factory.create_storage_target_platform()
#         )
#         self.ipu_storage_platform = self.platforms_factory.create_ipu_storage_platform()
#         self.host_target_platform = self.platforms_factory.create_host_target_platform()
#
#     def runTest(self):
#         self.assertTrue(
#             self.storage_target_platform.is_port_free(self.tests_config.nvme_port)
#         )
#         self.storage_target_platform.create_subsystem(
#             self.tests_config.nqn,
#             self.tests_config.nvme_port,
#             self.tests_config.spdk_port,
#         )
#         self.assertFalse(
#             self.storage_target_platform.is_port_free(self.tests_config.nvme_port)
#         )
#         self.assertTrue(
#             self.storage_target_platform.is_app_listening_on_port(
#                 "spdk_tgt", self.tests_config.nvme_port
#             )
#         )
#
#         remote_nvme_storages = self.storage_target_platform.create_ramdrives(
#             self.tests_config.max_ramdrive,
#             self.tests_config.nvme_port,
#             self.tests_config.nqn,
#             self.tests_config.spdk_port,
#         )
#         self.assertEqual(len(remote_nvme_storages), self.tests_config.max_ramdrive)
#
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(), 0
#         )
#         devices_handles = (
#             self.ipu_storage_platform.create_virtio_blk_devices_sequentially(
#                 self.host_target_platform.get_service_address(),
#                 remote_nvme_storages,
#             )
#         )
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(),
#             self.tests_config.max_ramdrive,
#         )
#
#         self.ipu_storage_platform.delete_virtio_blk_devices(devices_handles)
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(), 0
#         )
#
#     def tearDown(self):
#         self.platforms_factory.cmd_sender.stop()
#         self.ipu_storage_platform.clean()
#         self.storage_target_platform.clean()
#         self.host_target_platform.clean()
#
#
# class TestKVMAboveMaxHotPlug(BaseTest):
#     def setUp(self):
#         self.tests_config = TestConfig()
#         self.platforms_factory = PlatformFactory(self.tests_config.cmd_sender_platform)
#         self.storage_target_platform = (
#             self.platforms_factory.create_storage_target_platform()
#         )
#         self.ipu_storage_platform = self.platforms_factory.create_ipu_storage_platform()
#         self.host_target_platform = self.platforms_factory.create_host_target_platform()
#
#     def runTest(self):
#         self.assertTrue(
#             self.storage_target_platform.is_port_free(self.tests_config.nvme_port)
#         )
#         self.storage_target_platform.create_subsystem(
#             self.tests_config.nqn,
#             self.tests_config.nvme_port,
#             self.tests_config.spdk_port,
#         )
#         self.assertFalse(
#             self.storage_target_platform.is_port_free(self.tests_config.nvme_port)
#         )
#         self.assertTrue(
#             self.storage_target_platform.is_app_listening_on_port(
#                 "spdk_tgt", self.tests_config.nvme_port
#             )
#         )
#
#         remote_nvme_storages = self.storage_target_platform.create_ramdrives(
#             self.tests_config.max_ramdrive + 1,
#             self.tests_config.nvme_port,
#             self.tests_config.nqn,
#             self.tests_config.spdk_port,
#         )
#         self.assertGreater(len(remote_nvme_storages), self.tests_config.max_ramdrive)
#
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(), 0
#         )
#         self.assertRaises(
#             CommandException,
#             self.ipu_storage_platform.create_virtio_blk_devices_sequentially,
#             self.host_target_platform.get_service_address(),
#             remote_nvme_storages,
#         )
#
#     def tearDown(self):
#         self.platforms_factory.cmd_sender.stop()
#         self.ipu_storage_platform.clean()
#         self.storage_target_platform.clean()
#         self.host_target_platform.clean()


class TestOPIenv(BaseTest):
    def setUp(self):
        self.ssh_terminal = SSHTerminal(IPUStorageConfig())
        # self.clone_requirements = F"git clone https://github.com/spdk/spdk --recursive && "
        # F"git clone https://github.com/opiproject/opi-api && "
        # F"git clone https://github.com/opiproject/opi-intel-bridge && "
        # F"git clone https://github.com/opiproject/opi-spdk-bridge && "
        # F"git clone https://github.com/ipdk-io/ipdk"
        #
        # self.download_install_go = \
        #     F"""wget https://go.dev/dl/go1.19.5.linux-amd64.tar.gz && """
        # F"""rm -rf /usr/local/go && tar -C /usr/local -xzf go1.19.5.linux-amd64.tar.gz && """
        # F"""export PATH=$PATH:/usr/local/go/bin && """
        # F"""spdk/scripts/setup.sh"""

        # self.install_spdk_orerequisites = \
        #     """cd spdk && """
        # """dnf install kernel-headers && """
        # """./scripts/pkgdep.sh && """
        # """./configure --with-vfio-user && """
        # """make """
        #
        # self.run_kvm_server(
        #     f"cd opi-spdk-bridge &&"
        #     f"go run ./cmd -ctrlr_dir=/var/tmp -kvm -port 50052"
        # )
        # self.create_hugepages = \
        #     """echo 4096 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages"""
        self.run_spdk_sock = \
            "./spdk/build/bin/spdk_tgt -S /var/tmp -s 1024 -m 0x3"
        self.run_spdk_sock2 = "./spdk/build/bin/spdk_tgt -S /var/tmp -s 1024 -m 0x20 -r /var/tmp/spdk2.sock"
        self.create_transports = \
        f"cd spdk/scripts/ && " \
        f"./rpc.py -s /var/tmp/spdk2.sock nvmf_create_transport -t tcp && " \
        f"./rpc.py -s /var/tmp/spdk2.sock nvmf_create_transport -t vfiouser && " \
        f"./rpc.py nvmf_create_transport -t tcp && " \
        f"./rpc.py nvmf_create_transport -t vfiouser && " \
        f"cd -"

        self.create_vm = \
        f"/ipdk/build/storage/scripts/vm/install_qemu.sh && " \
        f"./ipdk/build/storage/scripts/vm/run_vm.sh"

        self.newterminal_mallock = \
        f"""export BRIDGE_ADDR="127.0.0.1:50052" """

        self.create_mallock= \
        f"cd spdk/scripts && "
        f"./rpc.py bdev_malloc_create -b Malloc0 16 4096"

        # self.send_opi_cmd_to_vm = \
        # f"""env -i grpc_cli --json_input --json_output call $BRIDGE_ADDR CreateVirtioBlk "{virtio_blk_id: 'virtioblk0',virtio_blk : { volume_id: {"""
        # f"""value: 'Malloc0'}, pcie_id: { physical_function: '0'} }}""""

        self.is_vm_created = f"ls /dev/vd*"
    def runTest(self):
        print(self.ssh_terminal.execute("ls"))
        self.ssh_terminal.execute(
            F"git clone https://github.com/spdk/spdk --recursive && "
            F"git clone https://github.com/opiproject/opi-api && "
            F"git clone https://github.com/opiproject/opi-intel-bridge && "
            F"git clone https://github.com/opiproject/opi-spdk-bridge && "
            F"git clone https://github.com/ipdk-io/ipdk")
        print(self.ssh_terminal.execute("ls"))
        print(self.ssh_terminal.execute("ls"))
        print(self.ssh_terminal.execute("ls"))
        self.ssh_terminal.execute(
            F"sudo dnf install docker-ce docker-ce-cli containerd.io libguestfs-tools-c grpc-cli"
        )

        self.ssh_terminal.execute(
            """cd spdk && """
            """dnf install kernel-headers && """
            """bash ./scripts/pkgdep.sh && """
            """./configure --with-vfio-user && """
            """make""")
        ###~~~~5 min wait time
        self.ssh_terminal.execute(
            F"""sudo su && """
            F"""wget https://go.dev/dl/go1.19.5.linux-amd64.tar.gz && """
            F"""rm -rf /usr/local/go && tar -C /usr/local -xzf go1.19.5.linux-amd64.tar.gz && """
            F"""export PATH=$PATH:/usr/local/go/bin""")
        print(self.ssh_terminal.execute("ls"))
        self.ssh_terminal.execute(f"cd opi-spdk-bridge &&"
                                  f"go run ./cmd -ctrlr_dir=/var/tmp -kvm -port 50052 &")
        print(self.ssh_terminal.execute("ls"))
        self.ssh_terminal.execute("echo 4096 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages")
        print(self.ssh_terminal.execute("ls"))

        # self.ssh_terminal.execute(self.clone_requirements)
        # self.ssh_terminal.execute(self.download_install_go)
        # self.ssh_terminal.execute(self.install_spdk_orerequisites)
        # self.ssh_terminal.execute(self.create_hugepages)

    def tearDown(self):
        pass
