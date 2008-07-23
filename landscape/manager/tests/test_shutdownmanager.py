from twisted.python.failure import Failure
from twisted.internet.error import ProcessTerminated

from landscape import API
from landscape.manager.manager import SUCCEEDED, FAILED
from landscape.manager.shutdownmanager import (
    ShutdownManager, ShutdownProcessProtocol)
from landscape.tests.helpers import (
    LandscapeTest, ManagerHelper, StubProcessFactory)


class ShutdownManagerTest(LandscapeTest):

    helpers = [ManagerHelper]

    def setUp(self):
        super(ShutdownManagerTest, self).setUp()
        self.broker_service.message_store.set_accepted_types(
            ["shutdown", "operation-result"])
        self.process_factory = StubProcessFactory()
        self.plugin = ShutdownManager(process_factory=self.process_factory)
        self.manager.add(self.plugin)

    def test_restart(self):
        """
        C{shutdown} processes run until the shutdown is to be performed.  The
        L{ShutdownProcessProtocol} watches a process for errors, for 10
        seconds by default, and if none occur the activity is marked as
        L{SUCCEEDED}.  Data printed by the process is included in the
        activity's result text.
        """
        message = {"type": "shutdown", "reboot": True, "operation-id": 100}
        self.plugin.perform_shutdown(message)
        [arguments] = self.process_factory.spawns
        protocol = arguments[0]
        self.assertTrue(isinstance(protocol, ShutdownProcessProtocol))
        self.assertEquals(
            arguments[1:3],
            ("/sbin/shutdown", ["/sbin/shutdown", "-r", "+4",
                                "Landscape is rebooting the system"]))

        def restart_performed(ignore):
            self.assertTrue(self.broker_service.exchanger.is_urgent())
            self.assertEquals(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result", "api": API,
                  "operation-id": 100, "timestamp": 10, "status": SUCCEEDED,
                  "result-text": u"Data may arrive in batches."}])

        protocol.result.addCallback(restart_performed)
        protocol.childDataReceived(0, "Data may arrive ")
        protocol.childDataReceived(0, "in batches.")
        self.manager.reactor.advance(10)
        return protocol.result

    def test_shutdown(self):
        """
        C{shutdown} messages have a flag that indicates whether a reboot or
        shutdown has been requested.  The C{shutdown} command is called
        appropriately.
        """
        message = {"type": "shutdown", "reboot": False, "operation-id": 100}
        self.plugin.perform_shutdown(message)
        [arguments] = self.process_factory.spawns
        self.assertEquals(
            arguments[1:3],
            ("/sbin/shutdown", ["/sbin/shutdown", "-h", "+4",
                                "Landscape is shutting down the system"]))

    def test_restart_fails(self):
        """
        If an error occurs before the error checking timeout the activity will
        be failed.  Data printed by the process prior to the failure is
        included in the activity's result text.
        """
        message = {"type": "shutdown", "reboot": False, "operation-id": 100}
        self.plugin.perform_shutdown(message)

        def restart_failed(message_id):
            self.assertTrue(self.broker_service.exchanger.is_urgent())
            self.assertEquals(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result", "api": API,
                  "operation-id": 100, "timestamp": 0, "status": FAILED,
                  "result-text": u"Failure text is reported."}])

        [arguments] = self.process_factory.spawns
        protocol = arguments[0]
        protocol.result.addCallback(restart_failed)
        protocol.childDataReceived(0, "Failure text is reported.")
        protocol.processEnded(Failure(ProcessTerminated(exitCode=1)))
        return protocol.result

    def test_process_ends_after_timeout(self):
        """
        If the process ends after the error checking timeout has passed
        C{result} will not be re-fired.
        """
        message = {"type": "shutdown", "reboot": False, "operation-id": 100}
        self.plugin.perform_shutdown(message)

        stash = []
        def restart_performed(ignore):
            self.assertEquals(stash, [])
            stash.append(True)

        [arguments] = self.process_factory.spawns
        protocol = arguments[0]
        protocol.result.addCallback(restart_performed)
        self.manager.reactor.advance(10)
        protocol.processEnded(Failure(ProcessTerminated(exitCode=1)))
        return protocol.result

    def test_process_data_is_not_collected_after_firing_result(self):
        """
        Data printed in the sub-process is not collected after C{result} has
        been fired.
        """
        message = {"type": "shutdown", "reboot": False, "operation-id": 100}
        self.plugin.perform_shutdown(message)

        [arguments] = self.process_factory.spawns
        protocol = arguments[0]
        protocol.childDataReceived(0, "Data may arrive ")
        protocol.childDataReceived(0, "in batches.")
        self.manager.reactor.advance(10)
        self.assertEquals(protocol.get_data(), "Data may arrive in batches.")
        protocol.childDataReceived(0, "Even when you least expect it.")
        self.assertEquals(protocol.get_data(), "Data may arrive in batches.")