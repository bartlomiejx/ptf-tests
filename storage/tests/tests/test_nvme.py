# # Copyright (C) 2022 Intel Corporation
# # SPDX-License-Identifier: Apache-2.0
# #
#
# target = "nvme"
# from system_tools.config import TestConfig, import_base_test
# from system_tools.const import FIO_COMMON, FIO_IO_PATTERNS
# from system_tools.errors import CommandException
# from system_tools.test_platform import PlatformFactory
#
# BaseTest = import_base_test(target)
#
#
# class TestNVMEMinHotPlugAndFio(BaseTest):
#     def setUp(self):
#         self.tests_config = TestConfig()
#         self.platforms_factory = PlatformFactory(self.tests_config.cmd_sender_platform)
#         self.storage_target_platform = (
#             self.platforms_factory.create_storage_target_platform()
#         )
#         self.ipu_storage_platform = self.platforms_factory.create_ipu_storage_platform()
#         self.host_target_platform = self.platforms_factory.create_host_target_platform()
#         self.cmd_sender = self.platforms_factory.cmd_sender
#
#     def runTest(self):
#         nvme_file_not_exist_response = (
#             "cannot access '/dev/nvme*': No such file or directory"
#         )
#         self.assertIn(
#             nvme_file_not_exist_response,
#             self.host_target_platform.check_nvme_dev_files(),
#         )
#         self.assertNotIn("nvme0n1", self.host_target_platform.check_block_devices())
#
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
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(), 0
#         )
#         malloc0 = remote_nvme_storages[0].guid
#         assert malloc0
#
#         device = self.ipu_storage_platform.create_nvme_device(
#             self.host_target_platform.get_service_address(), remote_nvme_storages[0], 0
#         )
#         nvme0 = device._device_handle
#         assert nvme0
#         self.assertNotIn(
#             nvme_file_not_exist_response,
#             self.host_target_platform.check_nvme_dev_files(),
#         )
#         self.assertNotIn("nvme0n1", self.host_target_platform.check_block_devices())
#         device.attach_volume(
#             self.cmd_sender,
#             self.storage_target_platform.get_ip_address(),
#             self.tests_config.nvme_port,
#         )
#         self.assertNotIn(
#             nvme_file_not_exist_response,
#             self.host_target_platform.check_nvme_dev_files(),
#         )
#         self.assertIn("nvme0n1", self.host_target_platform.check_block_devices())
#
#         for io_pattern in FIO_IO_PATTERNS:
#             fio_args = {
#                 **FIO_COMMON,
#                 "rw": io_pattern.lower(),
#             }
#             self.assertTrue(device.run_fio(fio_args))
#
#         device.detach_volume(self.cmd_sender)
#         self.assertNotIn(
#             nvme_file_not_exist_response,
#             self.host_target_platform.check_nvme_dev_files(),
#         )
#         self.assertNotIn("nvme0n1", self.host_target_platform.check_block_devices())
#
#         self.ipu_storage_platform.delete_virtio_blk_devices([device])
#         self.assertIn(
#             nvme_file_not_exist_response,
#             self.host_target_platform.check_nvme_dev_files(),
#         )
#         self.assertNotIn("nvme0n1", self.host_target_platform.check_block_devices())
#
#     def tearDown(self):
#         self.platforms_factory.cmd_sender.stop()
#         self.ipu_storage_platform.clean()
#         self.storage_target_platform.clean()
#         self.host_target_platform.clean()
#
#
# class TestNVMEMaxHotPlug(BaseTest):
#     def setUp(self):
#         self.tests_config = TestConfig()
#         self.platforms_factory = PlatformFactory(self.tests_config.cmd_sender_platform)
#         self.storage_target_platform = (
#             self.platforms_factory.create_storage_target_platform()
#         )
#         self.ipu_storage_platform = self.platforms_factory.create_ipu_storage_platform()
#         self.host_target_platform = self.platforms_factory.create_host_target_platform()
#         self.cmd_sender = self.platforms_factory.cmd_sender
#
#     def runTest(self):
#         nvme_file_not_exist_response = (
#             "cannot access '/dev/nvme*': No such file or directory"
#         )
#         self.assertIn(
#             nvme_file_not_exist_response,
#             self.host_target_platform.check_nvme_dev_files(),
#         )
#         self.assertNotIn("nvme0n1", self.host_target_platform.check_block_devices())
#
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
#         remote_nvme_storages = self.storage_target_platform.create_ramdrives(
#             self.tests_config.max_ramdrive,
#             self.tests_config.nvme_port,
#             self.tests_config.nqn,
#             self.tests_config.spdk_port,
#         )
#         self.assertEqual(len(remote_nvme_storages), self.tests_config.max_ramdrive)
#         self.assertEqual(
#             self.host_target_platform.get_number_of_virtio_blk_devices(), 0
#         )
#
#         devices_handles = self.ipu_storage_platform.create_nvme_devices_sequentially(
#             self.host_target_platform.get_service_address(),
#             remote_nvme_storages,
#         )
#         nvme0 = devices_handles[0]._device_handle
#         assert nvme0
#
#         self.assertNotIn(
#             nvme_file_not_exist_response,
#             self.host_target_platform.check_nvme_dev_files(),
#         )
#         self.assertEqual(
#             self.host_target_platform.vm.socket_terminal.execute(
#                 "ls /dev/nvme* | wc -l"
#             ),
#             "64",
#         )
#         self.assertEqual(
#             self.host_target_platform.vm.socket_terminal.execute(
#                 "lsblk | grep -c nvme"
#             ),
#             "0",
#         )
#         for device in devices_handles:
#             device.attach_volume(
#                 self.cmd_sender,
#                 self.storage_target_platform.get_ip_address(),
#                 self.tests_config.nvme_port,
#             )
#         self.assertEqual(
#             self.host_target_platform.vm.socket_terminal.execute(
#                 "lsblk | grep -c nvme"
#             ),
#             "64",
#         )
#         for device in devices_handles:
#             device.detach_volume(self.cmd_sender)
#         devices_handles2 = devices_handles[:32]
#
#         device_master = devices_handles[0]
#         remote_nvme_storage_master = device_master._remote_nvme_storage
#         for device in devices_handles2:
#             device_master._remote_nvme_storage = device._remote_nvme_storage
#             device_master.attach_volume(
#                 self.cmd_sender,
#                 self.storage_target_platform.get_ip_address(),
#                 self.tests_config.nvme_port,
#             )
#         device_master._remote_nvme_storage = remote_nvme_storage_master
#         self.assertEqual(
#             self.host_target_platform.vm.socket_terminal.execute(
#                 "lsblk | grep -c nvme0n*"
#             ),
#             "32",
#         )
#         for device in devices_handles2:
#             device_master._remote_nvme_storage = device._remote_nvme_storage
#             device_master.detach_volume(self.cmd_sender)
#         device_master._remote_nvme_storage = remote_nvme_storage_master
#         self.ipu_storage_platform.delete_virtio_blk_devices(devices_handles)
#
#         self.assertIn(
#             nvme_file_not_exist_response,
#             self.host_target_platform.check_nvme_dev_files(),
#         )
#         self.assertNotIn("nvme0n1", self.host_target_platform.check_block_devices())
#
#     def tearDown(self):
#         self.platforms_factory.cmd_sender.stop()
#         self.ipu_storage_platform.clean()
#         self.storage_target_platform.clean()
#         self.host_target_platform.clean()
#
#
# class TestNVMEAboveMaxHotPlug(BaseTest):
#     def setUp(self):
#         self.tests_config = TestConfig()
#         self.platforms_factory = PlatformFactory(self.tests_config.cmd_sender_platform)
#         self.storage_target_platform = (
#             self.platforms_factory.create_storage_target_platform()
#         )
#         self.ipu_storage_platform = self.platforms_factory.create_ipu_storage_platform()
#         self.host_target_platform = self.platforms_factory.create_host_target_platform()
#         self.cmd_sender = self.platforms_factory.cmd_sender
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
#
#         self.assertRaises(
#             CommandException,
#             self.ipu_storage_platform.create_nvme_devices_sequentially,
#             self.host_target_platform.get_service_address(),
#             remote_nvme_storages,
#         )
#
#     def tearDown(self):
#         self.platforms_factory.cmd_sender.stop()
#         self.ipu_storage_platform.clean()
#         self.storage_target_platform.clean()
#         self.host_target_platform.clean()
