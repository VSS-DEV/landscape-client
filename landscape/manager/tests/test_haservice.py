import os

from landscape.manager.haservice import HAService
from landscape.manager.plugin import SUCCEEDED, FAILED
from landscape.tests.helpers import LandscapeTest, ManagerHelper


class HAServiceTests(LandscapeTest):
    helpers = [ManagerHelper]

    def setUp(self):
        super(HAServiceTests, self).setUp()
        self.ha_service = HAService()
        self.ha_service.JUJU_UNITS_BASE = self.makeDir()
        self.unit_name = "my-service-9"

        self.health_check_d = os.path.join(
            self.ha_service.JUJU_UNITS_BASE, self.unit_name,
             self.ha_service.HEALTH_SCRIPTS_DIR)
        os.mkdir(os.path.join(self.ha_service.JUJU_UNITS_BASE, self.unit_name))
        os.mkdir(self.health_check_d)

        self.manager.add(self.ha_service)

        unit_dir = "%s/%s" % (self.ha_service.JUJU_UNITS_BASE, self.unit_name)
        cluster_online = file(
            "%s/add_to_cluster" % unit_dir, "w")
        cluster_online.write("#!/bin/bash\nexit 0")
        cluster_online.close()
        cluster_standby = file(
            "%s/remove_from_cluster" % unit_dir, "w")
        cluster_standby.write("#!/bin/bash\nexit 0")
        cluster_standby.close()

        os.chmod(
            "%s/add_to_cluster" % unit_dir, 0755)
        os.chmod(
            "%s/remove_from_cluster" % unit_dir, 0755)

        service = self.broker_service
        service.message_store.set_accepted_types(["operation-result"])

#        self.sourceslist._run_process = lambda cmd, args, *aarg, **kargs: None

    def test_invalid_server_service_state_request(self):
        """
        When the landscape server requests a C{service-state} other than
        'online' or 'standby' the client responds with the appropriate error.
        """
        logging_mock = self.mocker.replace("logging.error")
        logging_mock("Invalid cluster participation state requested BOGUS.")
        self.mocker.replay()

        self.manager.dispatch_message(
            {"type": "change-ha-service", "service-name": "my-service",
             "unit-name": self.unit_name, "service-state": "BOGUS",
             "operation-id": 1})

        service = self.broker_service
        self.assertMessages(
            service.message_store.get_pending_messages(),
            [{"type": "operation-result", "result-text":
              u"Invalid cluster participation state requested BOGUS.",
              "status": FAILED, "operation-id": 1}])

    def test_not_a_juju_computer(self):
        """
        When not a juju charmed computer, L{HAService} reponds with an error
        due to missing JUJU_UNITS_BASE dir.
        """
        self.ha_service.JUJU_UNITS_BASE = "/I/don't/exist"

        logging_mock = self.mocker.replace("logging.error")
        logging_mock("This computer is not deployed with juju. "
                     "Changing high-availability service not supported.")
        self.mocker.replay()

        self.manager.dispatch_message(
            {"type": "change-ha-service", "service-name": "my-service",
             "unit-name": self.unit_name,
             "service-state": self.ha_service.STATE_STANDBY,
             "operation-id": 1})

        service = self.broker_service
        self.assertMessages(
            service.message_store.get_pending_messages(),
            [{"type": "operation-result", "result-text":
              u"This computer is not deployed with juju. Changing "
              u"high-availability service not supported.",
              "status": FAILED, "operation-id": 1}])

    def test_incorrect_juju_unit(self):
        """
        When not the specific juju charmed computer, L{HAService} reponds
        with an error due to missing the JUJU_UNITS_BASE/$JUJU_UNIT dir.
        """
        logging_mock = self.mocker.replace("logging.error")
        logging_mock("This computer is not juju unit some-other-service-0. "
                     "Unable to modify high-availability services.")
        self.mocker.replay()

        self.manager.dispatch_message(
            {"type": "change-ha-service", "service-name": "some-other-service",
             "unit-name": "some-other-service-0", "service-state": "standby",
             "operation-id": 1})

        service = self.broker_service
        self.assertMessages(
            service.message_store.get_pending_messages(),
            [{"type": "operation-result", "result-text":
              u"This computer is not juju unit some-other-service-0. "
              u"Unable to modify high-availability services.",
              "status": FAILED, "operation-id": 1}])

    def test_wb_no_health_check_directory(self):
        """
        When unable to find a valid C{HEALTH_CHECK_DIR}, L{HAService} will
        succeed but log an informational message.
        """
        self.ha_service.HEALTH_SCRIPTS_DIR = "I/don't/exist"

        def should_not_be_called(result):
            self.fail(
                "_run_health_checks failed on absent health check directory.")

        def check_success_result(result):
            self.assertEqual(
                result,
                "Skipping juju charm health checks. No scripts at "
                "%s/%s/I/don't/exist." %
                (self.ha_service.JUJU_UNITS_BASE, self.unit_name))

        result = self.ha_service._run_health_checks(self.unit_name)
        result.addCallbacks(check_success_result, should_not_be_called)

    def test_wb_no_health_check_scripts(self):
        """
        When C{HEALTH_CHECK_DIR} exists but, no scripts exist, L{HAService}
        will log an informational message, but succeed.
        """
        # In setup we created a health check directory but placed no health
        # scripts in it.
        def should_not_be_called(result):
            self.fail(
                "_run_health_checks failed on empty health check directory.")

        def check_success_result(result):
            self.assertEqual(
                result,
                "Skipping juju charm health checks. No scripts at "
                "%s/%s/%s." %
                (self.ha_service.JUJU_UNITS_BASE, self.unit_name,
                 self.ha_service.HEALTH_SCRIPTS_DIR))

        result = self.ha_service._run_health_checks(self.unit_name)
        result.addCallbacks(check_success_result, should_not_be_called)

    def test_wb_failed_health_script(self):
        """
        L{HAService} runs all health check scripts found in the
        C{HEALTH_CHECK_DIR}. If any script fails, L{HAService} will return a
        deferred L{fail}.
        """
        def expected_failure(result):
            self.assertEqual(
                result,
                "Skipping juju charm health checks. No scripts at "
                "%s/%s/%s." %
                (self.ha_service.JUJU_UNITS_BASE, self.unit_name,
                 self.ha_service.HEALTH_SCRIPTS_DIR))

        def check_success_result(result):
            self.fail(
                "_run_health_checks succeded despite a failed health script.")

        health_script = file(
            "%s/my-health-script-1" % self.health_check_d, "w")
        health_script.write("#!/bin/bash\nexit 1")
        health_script.close()

        os.chmod("%s/my-health-script-1" % self.health_check_d, 0755)

        result = self.ha_service._run_health_checks(self.unit_name)
        result.addCallbacks(check_success_result, expected_failure)

    def test_failed_health_script(self):
        def check_success_result(result):
            self.fail(
                "_run_health_checks succeded despite a failed health script.")

        health_script = file(
            "%s/my-health-script-1" % self.health_check_d, "w")
        health_script.write("#!/bin/bash\nexit 1")
        health_script.close()

        os.chmod("%s/my-health-script-1" % self.health_check_d, 0755)

        result = self.ha_service._run_health_checks(self.unit_name)
        result.addCallbacks(check_success_result, expected_failure)

    def test_missing_cluster_standby_or_cluster_online_scripts(self):
        def should_not_be_called(result):
            self.fail(
                "_change_cluster_participation failed on absent charm script.")

        def check_success_result(result):
            self.assertEqual(
                result,
                "This computer is always a participant in its high-availabilty"
                " cluster. No juju charm cluster settings changed.")

        result = self.ha_service._change_cluster_participation(
            None, self.unit_name, self.ha_service.STATE_ONLINE)
        result.addCallbacks(check_success_result, should_not_be_called)

        # Now test the cluster standby script
        result = self.ha_service._change_cluster_participation(
            None, self.unit_name, self.ha_service.STATE_STANDBY)
        result.addCallbacks(check_success_result, should_not_be_called)

    def test_failed_cluster_standby_or_cluster_online_scripts(self):
        pass

    def test_run_success(self):
        self.manager.dispatch_message(
            {"type": "change-ha-service", "service-name": "my-service",
             "unit-name": self.unit_name,
             "service-state": self.ha_service.STATE_STANDBY, 
             "operation-id": 1})

        service = self.broker_service
        self.assertMessages(
            service.message_store.get_pending_messages(),
            [{"type": "operation-result", 
              "status": SUCCEEDED, "operation-id": 1}])
