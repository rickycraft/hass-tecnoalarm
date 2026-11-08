"""Integration behavior with mocked HA APIs and client responses, entirely offline."""

import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ha_stubs import HomeAssistantError, UpdateFailed, modules

# Make runs this suite in its own process, isolated from the protocol tests.
sys.modules.update(modules())
from custom_components.tecnoalarm import async_setup_entry, async_unload_entry
from custom_components.tecnoalarm import alarm_control_panel as alarms
from custom_components.tecnoalarm import binary_sensor as sensors
from custom_components.tecnoalarm.config_flow import TecnoalarmConfigFlow
from custom_components.tecnoalarm.coordinator import TecnoalarmCoordinator
from custom_components.tecnoalarm.const import CONF_PERSISTENT_CONNECTION, CONF_POLLING, CONF_POLLING_INTERVAL

from custom_components.tecnoalarm.client.auth import AuthenticationError

CONFIG = dict(host="192.0.2.10", port=10001, appid="0462",
              passphrase="never-output-this", user_code="0123")
DATA = {"source": "live", "provisional": True,
        "panel": {"model": "TP888", "alarm": True, "fault": False, "raw_status": "00" * 16},
        "programs": [{"index": 2, "number": 3, "name": "House", "state": "armed", "raw_status": 67}]}


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=asyncio.to_thread),
                                    config_entries=SimpleNamespace(
                                        async_forward_entry_setups=AsyncMock(),
                                        async_unload_platforms=AsyncMock(return_value=True),
                                        async_get_entry=MagicMock(),
                                        async_entry_for_domain_unique_id=MagicMock(return_value=None),
                                        async_update_entry=MagicMock(),
                                        async_schedule_reload=MagicMock()))
        self.entry = SimpleNamespace(entry_id="panel-id", data=CONFIG, options={},
                                     unique_id="192.0.2.10:10001", async_on_unload=MagicMock())
        self.hass.config_entries.async_get_entry.return_value = self.entry
        self.client = MagicMock()
        self.client.read_status.return_value = deepcopy(DATA)
        self.coordinator = TecnoalarmCoordinator(self.hass, self.entry, self.client)
        self.coordinator.data = deepcopy(DATA)
        self.entry.runtime_data = self.coordinator

    async def test_poll_executor_interval_and_failures(self):
        self.assertEqual(self.coordinator.update_interval, timedelta(seconds=30))
        self.assertEqual(await self.coordinator._async_update_data(), DATA)
        self.hass.async_add_executor_job.assert_awaited_once_with(self.client.read_status)
        for error in (AuthenticationError(), OSError(), EOFError(), ValueError()):
            self.client.read_status.side_effect = error
            with self.subTest(error=type(error)), self.assertRaises(UpdateFailed):
                await self.coordinator._async_update_data()

    async def test_program_states_and_local_control_rejection(self):
        entity = alarms.TecnoalarmProgram(self.coordinator, 2)
        for state, expected in (("idle", "disarmed"), ("armed", "armed_away"),
                                ("partial", "armed_custom_bypass"), ("pre_exit", "arming"),
                                ("exit", "arming"), ("partial_exit", "arming"),
                                ("partial_end", None), ("unknown", None)):
            self.coordinator.data["programs"][0]["state"] = state
            self.assertEqual(entity.alarm_state, expected)
        self.assertEqual(entity.extra_state_attributes["raw_status"], 67)
        self.assertEqual(entity._attr_supported_features, 0)
        self.assertEqual(entity.name, "House")
        self.assertEqual(entity.device_info["model"], "TP888")
        self.client.reset_mock()
        for action in ("disarm", "arm_away", "arm_home", "arm_night", "arm_vacation",
                       "arm_custom_bypass", "trigger"):
            with self.assertRaisesRegex(HomeAssistantError, "read-only"):
                await getattr(entity, f"async_alarm_{action}")(code="9999")
        self.assertEqual(self.client.mock_calls, [])

    async def test_keep_alive_executor_and_failure_recovery(self):
        await self.coordinator.async_keep_alive(None)
        self.hass.async_add_executor_job.assert_awaited_once_with(self.client.keep_alive)
        for error in (OSError(), EOFError(), ValueError()):
            self.client.keep_alive.side_effect = error
            await self.coordinator.async_keep_alive(None)
            self.assertFalse(self.coordinator._keep_alive_running)
        self.coordinator._keep_alive_running = True
        self.client.keep_alive.reset_mock()
        await self.coordinator.async_keep_alive(None)
        self.client.keep_alive.assert_not_called()

    async def test_availability_and_panel_alarm_separation(self):
        program = alarms.TecnoalarmProgram(self.coordinator, 2)
        alarm = sensors.TecnoalarmPanelSensor(self.coordinator, "alarm")
        fault = sensors.TecnoalarmPanelSensor(self.coordinator, "fault")
        self.assertEqual(program.alarm_state, "armed_away")
        self.assertTrue(alarm.is_on)
        self.assertFalse(fault.is_on)
        self.coordinator.last_update_success = False
        self.assertFalse(program.available)
        self.assertFalse(alarm.available)
        self.coordinator.last_update_success = True
        self.coordinator.data["programs"] = []
        self.assertFalse(program.available)
        self.assertIsNone(program.alarm_state)
        self.assertTrue(alarm.available)

    async def test_platforms_add_only_accessible_and_new_programs(self):
        add = MagicMock()
        await alarms.async_setup_entry(self.hass, self.entry, add)
        self.assertEqual([p.index for p in add.call_args.args[0]], [2])
        add.reset_mock()
        self.coordinator.listeners[0]()
        add.assert_not_called()
        self.coordinator.data["programs"].append(DATA["programs"][0] | {"index": 4})
        self.coordinator.listeners[0]()
        self.assertEqual([p.index for p in add.call_args.args[0]], [4])
        add.reset_mock()
        await sensors.async_setup_entry(self.hass, self.entry, add)
        self.assertEqual([p.key for p in add.call_args.args[0]], ["alarm", "fault"])

    async def test_setup_form_and_authenticated_entry(self):
        flow = TecnoalarmConfigFlow()
        flow.hass = self.hass
        result = await flow.async_step_user()
        self.assertEqual(result["type"], "form")
        self.assertEqual(set(result["data_schema"]), set(CONFIG) | {CONF_POLLING_INTERVAL})
        with patch("custom_components.tecnoalarm.config_flow.Client") as client:
            result = await flow.async_step_user(CONFIG)
            self.assertEqual(result["type"], "create_entry")
            client.return_value.authenticate.assert_called_once_with()
            self.assertEqual(result["data"], CONFIG)
            self.assertEqual(flow.unique_id, "192.0.2.10:10001")

    async def test_setup_errors_never_create_entry(self):
        flow = TecnoalarmConfigFlow()
        flow.hass = self.hass
        for error, expected in ((AuthenticationError(), "invalid_auth"), (OSError(), "cannot_connect"),
                                (EOFError(), "cannot_connect")):
            with patch("custom_components.tecnoalarm.config_flow.Client") as client:
                client.return_value.authenticate.side_effect = error
                result = await flow.async_step_user(CONFIG)
                self.assertEqual(result["type"], "form")
                self.assertEqual(result["errors"], {"base": expected})
        with patch("custom_components.tecnoalarm.client.auth.socket.create_connection") as connect:
            result = await flow.async_step_user(CONFIG | {"user_code": ""})
            self.assertEqual(result["errors"], {"base": "invalid_config"})
            connect.assert_not_called()

    async def test_polling_choice_saved_during_setup(self):
        for polling in (0, 1, 30, 600):
            with self.subTest(polling=polling), \
                    patch("custom_components.tecnoalarm.config_flow.Client") as client:
                flow = TecnoalarmConfigFlow()
                flow.hass = self.hass
                result = await flow.async_step_user(CONFIG | {CONF_POLLING_INTERVAL: polling})
                self.assertEqual(result["data"], CONFIG)
                self.assertEqual(result["options"], {CONF_POLLING_INTERVAL: polling})
                client.assert_called_once_with(**CONFIG)

    async def test_invalid_intervals_never_authenticate_or_pause_monitoring(self):
        for kind in ("user", "reconfigure", "options"):
            for interval in (-1, 601, 1.5, True, "30", None):
                with self.subTest(kind=kind, interval=interval):
                    flow = TecnoalarmConfigFlow()
                    flow.hass = self.hass
                    flow.context = {"source": "reconfigure", "entry_id": self.entry.entry_id}
                    if kind == "options":
                        flow = flow.async_get_options_flow(self.entry)
                        flow.hass = self.hass
                        flow.config_entry = self.entry
                    step = getattr(flow, "async_step_init" if kind == "options"
                                   else f"async_step_{kind}")
                    with patch("custom_components.tecnoalarm.config_flow.Client") as client:
                        result = await step(CONFIG | {CONF_POLLING_INTERVAL: interval})
                        self.assertEqual(result["errors"], {"base": "invalid_config"})
                        client.assert_not_called()
                    self.client.disconnect.assert_not_called()
                    self.hass.config_entries.async_update_entry.assert_not_called()

    async def test_default_polling_interval_is_30(self):
        flow = TecnoalarmConfigFlow()
        flow.hass = self.hass
        with patch("custom_components.tecnoalarm.config_flow.vol.Required",
                   side_effect=lambda key, **kwargs: key) as required:
            await flow.async_step_user()
            required.assert_any_call(CONF_POLLING_INTERVAL, default=30)
        with patch("custom_components.tecnoalarm.config_flow.Client"):
            result = await flow.async_step_user(CONFIG)
            self.assertEqual(result["options"], {CONF_POLLING_INTERVAL: 30})

    async def test_polling_can_be_changed_in_reconfigure_and_options(self):
        for polling in (0, 1, 30, 600):
            with self.subTest(polling=polling):
                self.entry.options = {CONF_POLLING_INTERVAL: 120,
                                      "future_option": 1}
                flow = TecnoalarmConfigFlow()
                flow.hass = self.hass
                flow.context = {"source": "reconfigure", "entry_id": self.entry.entry_id}
                with patch.object(flow, "add_suggested_values_to_schema",
                                  side_effect=lambda schema, values: schema) as suggested:
                    await flow.async_step_reconfigure()
                    self.assertEqual(suggested.call_args.args[1][CONF_POLLING_INTERVAL], 120)
                with patch("custom_components.tecnoalarm.config_flow.Client") as client:
                    await flow.async_step_reconfigure(CONFIG | {CONF_POLLING_INTERVAL: polling})
                    client.assert_called_once_with(**CONFIG)
                self.assertEqual(self.hass.config_entries.async_update_entry.call_args.kwargs[
                    "options"], {**self.entry.options, CONF_POLLING_INTERVAL: polling})
                options_flow = flow.async_get_options_flow(self.entry)
                options_flow.config_entry = self.entry
                options_flow.hass = self.hass
                with patch.object(options_flow, "add_suggested_values_to_schema",
                                  side_effect=lambda schema, values: schema) as suggested:
                    await options_flow.async_step_init()
                    self.assertEqual(suggested.call_args.args[1][CONF_POLLING_INTERVAL], 120)
                with patch("custom_components.tecnoalarm.config_flow.Client") as client:
                    result = await options_flow.async_step_init(CONFIG | {
                        CONF_POLLING_INTERVAL: polling})
                    client.assert_called_once_with(**CONFIG)
                self.assertEqual(result["data"], {**self.entry.options, CONF_POLLING_INTERVAL: polling})

    async def test_polling_intervals_keep_initial_and_manual_refresh(self):
        for polling in (0, 1, 30, 600):
            with self.subTest(polling=polling):
                self.entry.options = {CONF_POLLING_INTERVAL: polling}
                coordinator = TecnoalarmCoordinator(self.hass, self.entry, self.client)
                self.assertEqual(coordinator.update_interval,
                                 timedelta(seconds=polling or 30))
                self.assertEqual(await coordinator._async_update_data(), DATA)
                with patch("custom_components.tecnoalarm.client.Client"), \
                        patch("custom_components.tecnoalarm.coordinator.TecnoalarmCoordinator") as coord:
                    coord.return_value.async_config_entry_first_refresh = AsyncMock()
                    await async_setup_entry(self.hass, self.entry)
                    coord.return_value.async_config_entry_first_refresh.assert_awaited_once()

    async def test_reconfigure_shows_saved_values_and_keeps_failed_input(self):
        flow = TecnoalarmConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "reconfigure", "entry_id": self.entry.entry_id}
        changed = CONFIG | {"host": "192.0.2.20"}
        with patch.object(flow, "add_suggested_values_to_schema",
                          side_effect=lambda schema, values: schema) as suggested:
            result = await flow.async_step_reconfigure()
            self.assertEqual(result["step_id"], "reconfigure")
            self.assertEqual(set(result["data_schema"]),
                             set(CONFIG) | {CONF_POLLING_INTERVAL})
            self.assertEqual(suggested.call_args.args[1], CONFIG | {
                CONF_POLLING_INTERVAL: 30})
            with patch("custom_components.tecnoalarm.config_flow.Client") as client:
                for error, expected in ((AuthenticationError(), "invalid_auth"),
                                        (OSError(), "cannot_connect"),
                                        (EOFError(), "cannot_connect"),
                                        (ValueError(), "invalid_config")):
                    with self.subTest(error=type(error)):
                        client.return_value.authenticate.side_effect = error
                        result = await flow.async_step_reconfigure(changed)
                        self.assertEqual(result["type"], "form")
                        self.assertEqual(result["step_id"], "reconfigure")
                        self.assertEqual(result["errors"], {"base": expected})
                        self.assertEqual(suggested.call_args.args[1], changed)
            self.hass.config_entries.async_update_entry.assert_not_called()
            self.hass.config_entries.async_schedule_reload.assert_not_called()

    async def test_reconfigure_updates_existing_entry_and_reloads(self):
        for changes in ({"user_code": "4567", "passphrase": "replacement-secret"},
                        {"host": "Panel.Example", "port": 10002, "appid": "0463"}):
            with self.subTest(changes=list(changes)):
                flow = TecnoalarmConfigFlow()
                flow.hass = self.hass
                flow.context = {"source": "reconfigure", "entry_id": self.entry.entry_id}
                self.entry.options = {CONF_PERSISTENT_CONNECTION: False}
                changed = CONFIG | changes
                with patch("custom_components.tecnoalarm.config_flow.Client") as client, \
                        patch.object(flow, "_abort_if_unique_id_configured") as duplicate, \
                        patch.object(flow, "async_create_entry") as create:
                    result = await flow.async_step_reconfigure(changed)
                    self.assertEqual(result, {"type": "abort", "reason": "reconfigure_successful"})
                    client.assert_called_once_with(**changed)
                    client.return_value.authenticate.assert_called_once_with()
                    self.hass.async_add_executor_job.assert_awaited_with(
                        client.return_value.authenticate)
                    if "host" in changes:
                        duplicate.assert_called_once_with()
                    else:
                        duplicate.assert_not_called()
                    create.assert_not_called()
                self.hass.config_entries.async_update_entry.assert_called_with(
                    self.entry, unique_id=f"{changed['host'].lower()}:{changed['port']}",
                    title=f"Tecnoalarm {changed['host']}", data=changed,
                    options={CONF_POLLING_INTERVAL: 30})
                self.hass.config_entries.async_schedule_reload.assert_called_with(self.entry.entry_id)
                self.assertEqual(self.entry.options, {CONF_PERSISTENT_CONNECTION: False})

    async def test_reconfigure_duplicate_endpoint_never_authenticates_or_updates(self):
        flow = TecnoalarmConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "reconfigure", "entry_id": self.entry.entry_id}
        with patch("custom_components.tecnoalarm.config_flow.Client") as client, \
                patch.object(flow, "_abort_if_unique_id_configured",
                             side_effect=RuntimeError("already_configured")):
            with self.assertRaisesRegex(RuntimeError, "already_configured"):
                await flow.async_step_reconfigure(CONFIG | {"host": "192.0.2.20"})
            client.return_value.authenticate.assert_not_called()
        self.hass.config_entries.async_update_entry.assert_not_called()
        self.hass.config_entries.async_schedule_reload.assert_not_called()

    async def test_reconfiguration_pauses_traffic_and_resumes_only_on_failure(self):
        for options_flow in (False, True):
            for failure in (None, AuthenticationError(), OSError()):
                with self.subTest(options_flow=options_flow, failure=failure):
                    self.coordinator = TecnoalarmCoordinator(self.hass, self.entry, self.client)
                    self.coordinator.data = deepcopy(DATA)
                    self.entry.runtime_data = self.coordinator
                    self.client.reset_mock()
                    started, finish = asyncio.Event(), asyncio.Event()
                    with patch("custom_components.tecnoalarm.config_flow.Client") as client:
                        async def execute(func):
                            if func == client.return_value.authenticate:
                                self.client.disconnect.assert_called_once_with()
                                started.set()
                                await finish.wait()
                                if failure:
                                    raise failure
                            return func()

                        self.hass.async_add_executor_job.side_effect = execute
                        flow = TecnoalarmConfigFlow()
                        flow.hass = self.hass
                        flow.context = {"source": "reconfigure", "entry_id": self.entry.entry_id}
                        if options_flow:
                            flow = flow.async_get_options_flow(self.entry)
                            flow.hass = self.hass
                            flow.config_entry = self.entry
                        step = flow.async_step_init if options_flow else flow.async_step_reconfigure
                        # Merely opening the panel must leave monitoring running.
                        await step()
                        self.client.disconnect.assert_not_called()
                        submit = asyncio.create_task(step(CONFIG | {
                            CONF_POLLING_INTERVAL: 30}))
                        await asyncio.wait_for(started.wait(), 1)
                        poll = asyncio.create_task(self.coordinator._async_update_data())
                        keepalive = asyncio.create_task(self.coordinator.async_keep_alive(None))
                        await asyncio.sleep(0)
                        self.client.read_status.assert_not_called()
                        self.client.keep_alive.assert_not_called()
                        finish.set()
                        result = await submit
                        await asyncio.gather(poll, keepalive)
                        if failure:
                            self.assertEqual(result["type"], "form")
                            self.client.read_status.assert_called_once_with()
                            self.client.keep_alive.assert_called_once_with()
                        else:
                            self.assertIn(result["type"], ("abort", "create_entry"))
                            await self.coordinator._async_update_data()
                            await self.coordinator.async_keep_alive(None)
                            self.client.read_status.assert_not_called()
                            self.client.keep_alive.assert_not_called()

    async def test_reconfiguration_waits_for_inflight_panel_operations(self):
        for operation in (self.client.read_status, self.client.keep_alive):
            with self.subTest(operation=operation):
                coordinator = TecnoalarmCoordinator(self.hass, self.entry, self.client)
                started, finish = asyncio.Event(), asyncio.Event()
                async def execute(func):
                    if func == operation:
                        started.set()
                        await finish.wait()
                    return func()
                self.hass.async_add_executor_job.side_effect = execute
                active = asyncio.create_task(coordinator._async_update_data()
                    if operation == self.client.read_status else coordinator.async_keep_alive(None))
                await asyncio.wait_for(started.wait(), 1)
                validation_client = MagicMock()
                validation = asyncio.create_task(
                    coordinator.async_authenticate_for_reconfiguration(validation_client))
                await asyncio.sleep(0)
                validation_client.authenticate.assert_not_called()
                finish.set()
                await asyncio.gather(active, validation)
                validation_client.authenticate.assert_called_once_with()

    async def test_cancelled_validation_waits_before_resuming_monitoring(self):
        started, finish = asyncio.Event(), asyncio.Event()
        validation_client = MagicMock()
        async def execute(func):
            if func == validation_client.authenticate:
                started.set()
                await finish.wait()
            return func()
        self.hass.async_add_executor_job.side_effect = execute
        validation = asyncio.create_task(
            self.coordinator.async_authenticate_for_reconfiguration(validation_client))
        await asyncio.wait_for(started.wait(), 1)
        validation.cancel()
        await asyncio.sleep(0)
        self.assertFalse(validation.done())
        poll = asyncio.create_task(self.coordinator._async_update_data())
        await asyncio.sleep(0)
        self.client.read_status.assert_not_called()
        finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await validation
        await poll
        self.client.read_status.assert_called_once_with()

    async def test_reconfigure_unloaded_entry_validates_directly(self):
        del self.entry.runtime_data
        flow = TecnoalarmConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "reconfigure", "entry_id": self.entry.entry_id}
        with patch("custom_components.tecnoalarm.config_flow.Client") as client:
            result = await flow.async_step_reconfigure(CONFIG)
            self.assertEqual(result["type"], "abort")
            client.return_value.authenticate.assert_called_once_with()

    async def test_entry_lifecycle_and_first_refresh_failure(self):
        self.entry.options = {CONF_POLLING_INTERVAL: 0}
        with patch("custom_components.tecnoalarm.client.Client") as client, \
                patch("custom_components.tecnoalarm.coordinator.TecnoalarmCoordinator") as coord, \
                patch("homeassistant.helpers.event.async_track_time_interval") as track:
            coord.return_value.async_config_entry_first_refresh = AsyncMock()
            self.assertTrue(await async_setup_entry(self.hass, self.entry))
            coord.return_value.client = client.return_value
            client.assert_called_once_with(**CONFIG, persistent_connection=True)
            coord.return_value.async_config_entry_first_refresh.assert_awaited_once()
            self.hass.config_entries.async_forward_entry_setups.assert_awaited_once()
            track.assert_called_once_with(self.hass, coord.return_value.async_keep_alive,
                                          timedelta(seconds=5))
            self.entry.async_on_unload.assert_called_once_with(track.return_value)
            self.assertTrue(await async_unload_entry(self.hass, self.entry))
            self.hass.config_entries.async_unload_platforms.assert_awaited_once()
            client.return_value.close.assert_called_once_with()
            client.return_value.close.reset_mock()
            self.hass.config_entries.async_unload_platforms.return_value = False
            self.assertFalse(await async_unload_entry(self.hass, self.entry))
            client.return_value.close.assert_not_called()
            self.hass.config_entries.async_forward_entry_setups.reset_mock()
            coord.return_value.async_config_entry_first_refresh.side_effect = UpdateFailed()
            with self.assertRaises(UpdateFailed):
                await async_setup_entry(self.hass, self.entry)
            self.hass.config_entries.async_forward_entry_setups.assert_not_awaited()
            client.return_value.close.assert_called_once_with()

    async def test_forwarding_failure_closes_client(self):
        with patch("custom_components.tecnoalarm.client.Client") as client, \
                patch("custom_components.tecnoalarm.coordinator.TecnoalarmCoordinator") as coord:
            coord.return_value.async_config_entry_first_refresh = AsyncMock()
            self.hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError()
            with self.assertRaises(RuntimeError):
                await async_setup_entry(self.hass, self.entry)
            client.return_value.close.assert_called_once_with()

    async def test_connection_options_show_current_value_and_save(self):
        for options, expected in (({}, 30), ({CONF_POLLING_INTERVAL: 0}, 0),
                                  ({CONF_POLLING_INTERVAL: 600}, 600),
                                  ({CONF_PERSISTENT_CONNECTION: False, CONF_POLLING: True}, 30),
                                  ({CONF_PERSISTENT_CONNECTION: True, CONF_POLLING: True}, 0)):
            with self.subTest(options=options), \
                    patch("custom_components.tecnoalarm.config_flow.vol.Required",
                          side_effect=lambda key, **kwargs: key) as required, \
                    patch("custom_components.tecnoalarm.config_flow.Client") as client:
                self.entry.options = options
                flow = TecnoalarmConfigFlow.async_get_options_flow(self.entry)
                flow.config_entry = self.entry
                flow.hass = self.hass
                with patch.object(flow, "add_suggested_values_to_schema",
                                  side_effect=lambda schema, values: schema) as suggested:
                    result = await flow.async_step_init()
                    self.assertEqual(suggested.call_args.args[1], {
                        **CONFIG, CONF_POLLING_INTERVAL: expected})
                self.assertEqual(result["type"], "form")
                self.assertEqual(set(result["data_schema"]), set(CONFIG) | {CONF_POLLING_INTERVAL})
                required.assert_any_call(CONF_POLLING_INTERVAL, default=expected)
                changed = CONFIG | {"host": "Panel.Example", "port": 10002, "appid": "1234",
                                    "passphrase": "updated-secret", "user_code": "4567"}
                saved = await flow.async_step_init(changed | {CONF_POLLING_INTERVAL: 120})
                client.assert_called_once_with(**changed)
                client.return_value.authenticate.assert_called_once_with()
                self.hass.config_entries.async_entry_for_domain_unique_id.assert_called_with(
                    "tecnoalarm", "panel.example:10002")
                self.assertEqual(saved["type"], "create_entry")
                self.assertEqual(saved["data"], {CONF_POLLING_INTERVAL: 120})
                self.hass.config_entries.async_update_entry.assert_called_with(
                    self.entry, data=changed, options={CONF_POLLING_INTERVAL: 120},
                    unique_id="panel.example:10002", title="Tecnoalarm Panel.Example")
                self.hass.config_entries.async_schedule_reload.assert_called_with(self.entry.entry_id)

    async def test_connection_options_failures_keep_saved_settings_and_submitted_values(self):
        flow = TecnoalarmConfigFlow.async_get_options_flow(self.entry)
        flow.config_entry = self.entry
        flow.hass = self.hass
        submitted = CONFIG | {"host": "192.0.2.20", CONF_POLLING_INTERVAL: 600}
        with patch("custom_components.tecnoalarm.config_flow.Client") as client, \
                patch.object(flow, "add_suggested_values_to_schema",
                             side_effect=lambda schema, values: schema) as suggested:
            for error, expected in ((AuthenticationError(), "invalid_auth"),
                                    (OSError(), "cannot_connect"), (EOFError(), "cannot_connect"),
                                    (ValueError(), "invalid_config")):
                with self.subTest(error=type(error)):
                    client.return_value.authenticate.side_effect = error
                    result = await flow.async_step_init(submitted)
                    self.assertEqual(result["errors"], {"base": expected})
                    self.assertEqual(suggested.call_args.args[1], submitted)
            client.return_value.authenticate.reset_mock(side_effect=True)
            self.hass.config_entries.async_entry_for_domain_unique_id.return_value = SimpleNamespace(
                entry_id="another-panel")
            result = await flow.async_step_init(submitted)
            self.assertEqual(result["errors"], {"base": "already_configured"})
            client.return_value.authenticate.assert_not_called()
        self.hass.config_entries.async_update_entry.assert_not_called()
        self.hass.config_entries.async_schedule_reload.assert_not_called()

    async def test_connection_options_credentials_only_reload_and_preserve_other_options(self):
        flow = TecnoalarmConfigFlow.async_get_options_flow(self.entry)
        flow.config_entry = self.entry
        flow.hass = self.hass
        self.entry.options = {CONF_POLLING_INTERVAL: 0, "future_option": 1}
        self.hass.config_entries.async_entry_for_domain_unique_id.return_value = self.entry
        changed = CONFIG | {"user_code": "4567"}
        with patch("custom_components.tecnoalarm.config_flow.Client"):
            result = await flow.async_step_init(changed | {CONF_POLLING_INTERVAL: 0})
        self.assertEqual(result["data"], self.entry.options)
        self.hass.config_entries.async_update_entry.assert_called_once_with(
            self.entry, data=changed, options=self.entry.options,
            unique_id=self.entry.unique_id, title=f"Tecnoalarm {CONFIG['host']}")
        self.hass.config_entries.async_schedule_reload.assert_called_once_with(self.entry.entry_id)

    async def test_connection_modes_apply_on_setup_and_reload(self):
        for interval in (0, 1, 30, 600):
            persistent = interval == 0
            with self.subTest(interval=interval), \
                    patch("custom_components.tecnoalarm.client.Client") as client, \
                    patch("custom_components.tecnoalarm.coordinator.TecnoalarmCoordinator") as coord, \
                    patch("homeassistant.helpers.event.async_track_time_interval") as track:
                self.entry.options = {CONF_POLLING_INTERVAL: interval}
                coord.return_value.async_config_entry_first_refresh = AsyncMock()
                coord.return_value.client = client.return_value
                self.assertTrue(await async_setup_entry(self.hass, self.entry))
                client.assert_called_once_with(**CONFIG, persistent_connection=persistent)
                if persistent:
                    track.assert_called_once()
                else:
                    track.assert_not_called()
                self.assertTrue(await async_unload_entry(self.hass, self.entry))
                client.return_value.close.assert_called_once_with()

    def test_installation_metadata(self):
        root = Path(__file__).resolve().parents[1] / "custom_components/tecnoalarm"
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["domain"], "tecnoalarm")
        self.assertEqual(manifest["iot_class"], "local_polling")
        self.assertEqual(json.loads((root / "strings.json").read_text()),
                         json.loads((root / "translations/en.json").read_text()))


if __name__ == "__main__":
    unittest.main()
