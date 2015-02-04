# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for ``flocker.node._loop``.
"""

from twisted.trial.unittest import SynchronousTestCase
from twisted.test.proto_helpers import StringTransport
from twisted.internet.protocol import Protocol

from .._loop import (
    build_cluster_status_fsm, ClusterStatusInputs, _ClientStatusUpdate,
    _StatusUpdate, _ClientConnected, ConvergenceLoopInputs
    )


def build_protocol():
    """
    :return: ``Protocol`` hooked up to transport.
    """
    p = Protocol()
    p.makeConnection(StringTransport())
    return p


class StubFSM(object):
    """
    A finite state machine look-alike that just records inputs.
    """
    def __init__(self):
        self.inputted = []

    def receive(self, symbol):
        self.inputted.append(symbol)


class ClusterStatusFSMTests(SynchronousTestCase):
    """
    Tests for the cluster status FSM.
    """
    def setUp(self):
        self.agent_operation = StubFSM()
        self.fsm = build_cluster_status_fsm(self.agent_operation)

    def assertConvergenceLoopInputted(self, expected):
        """
        Assert that that given set of symbols were input to the agent
        operation FSM.
        """
        self.assertEqual(self.agent_operation.inputted, expected)

    def test_creation_no_side_effects(self):
        """
        Creating the FSM has no side effects.
        """
        self.assertConvergenceLoopInputted([])

    def test_first_status_update(self):
        """
        Once the client has been connected and a status update received it
        notifies the agent operation FSM of this.
        """
        client = object()
        desired = object()
        state = object()
        self.fsm.receive(_ClientConnected(client=client))
        self.fsm.receive(_StatusUpdate(configuration=desired, state=state))
        self.assertConvergenceLoopInputted(
            [_ClientStatusUpdate(client=client, configuration=desired,
                                 state=state)])

    def test_second_status_update(self):
        """
        Further status updates are also passed to the agent operation FSM.
        """
        client = object()
        desired1 = object()
        state1 = object()
        desired2 = object()
        state2 = object()
        self.fsm.receive(_ClientConnected(client=client))
        # Initially some other status:
        self.fsm.receive(_StatusUpdate(configuration=desired1, state=state1))
        self.fsm.receive(_StatusUpdate(configuration=desired2, state=state2))
        self.assertConvergenceLoopInputted(
            [_ClientStatusUpdate(client=client, configuration=desired1,
                                 state=state1),
             _ClientStatusUpdate(client=client, configuration=desired2,
                                 state=state2)])

    def test_status_update_no_disconnect(self):
        """
        Neither new connections nor status updates cause the client to be
        disconnected.
        """
        client = build_protocol()
        self.fsm.receive(_ClientConnected(client=client))
        self.fsm.receive(_StatusUpdate(configuration=object(),
                                       state=object()))
        self.assertFalse(client.transport.disconnecting)

    def test_disconnect_before_status_update(self):
        """
        If the client disconnects before a status update is received then no
        notification is needed for agent operation FSM.
        """
        self.fsm.receive(_ClientConnected(client=build_protocol()))
        self.fsm.receive(ClusterStatusInputs.CLIENT_DISCONNECTED)
        self.assertConvergenceLoopInputted([])

    def test_disconnect_after_status_update(self):
        """
        If the client disconnects after a status update is received then the
        agent operation is FSM is notified.
        """
        client = object()
        desired = object()
        state = object()
        self.fsm.receive(_ClientConnected(client=client))
        self.fsm.receive(_StatusUpdate(configuration=desired, state=state))
        self.fsm.receive(ClusterStatusInputs.CLIENT_DISCONNECTED)
        self.assertConvergenceLoopInputted(
            [_ClientStatusUpdate(client=client, configuration=desired,
                                 state=state),
             ConvergenceLoopInputs.STOP])

    def test_status_update_after_reconnect(self):
        """
        If the client disconnects, reconnects, and a new status update is
        received then the agent operation FSM is notified.
        """
        client = object()
        desired = object()
        state = object()
        self.fsm.receive(_ClientConnected(client=client))
        self.fsm.receive(_StatusUpdate(configuration=desired, state=state))
        self.fsm.receive(ClusterStatusInputs.CLIENT_DISCONNECTED)
        client2 = object()
        desired2 = object()
        state2 = object()
        self.fsm.receive(_ClientConnected(client=client2))
        self.fsm.receive(_StatusUpdate(configuration=desired2, state=state2))
        self.assertConvergenceLoopInputted(
            [_ClientStatusUpdate(client=client, configuration=desired,
                                 state=state),
             ConvergenceLoopInputs.STOP,
             _ClientStatusUpdate(client=client2, configuration=desired2,
                                 state=state2)])

    def test_shutdown_before_connect(self):
        """
        If the FSM is shutdown before a connection is made nothing happens.
        """
        self.fsm.receive(ClusterStatusInputs.SHUTDOWN)
        self.assertConvergenceLoopInputted([])

    def test_shutdown_after_connect(self):
        """
        If the FSM is shutdown after connection but before status update is
        received then it disconnects but does not notify the agent
        operation FSM.
        """
        client = build_protocol()
        self.fsm.receive(_ClientConnected(client=client))
        self.fsm.receive(ClusterStatusInputs.SHUTDOWN)
        self.assertEqual((client.transport.disconnecting,
                          self.agent_operation.inputted),
                         (True, []))

    def test_shutdown_after_status_update(self):
        """
        If the FSM is shutdown after connection and status update is received
        then it disconnects and also notifys the agent operation FSM that
        is should stop.
        """
        client = build_protocol()
        desired = object()
        state = object()
        self.fsm.receive(_ClientConnected(client=client))
        self.fsm.receive(_StatusUpdate(configuration=desired, state=state))
        self.fsm.receive(ClusterStatusInputs.SHUTDOWN)
        self.assertEqual((client.transport.disconnecting,
                          self.agent_operation.inputted[-1]),
                         (True, ConvergenceLoopInputs.STOP))

    def test_shutdown_fsm_ignores_disconnection(self):
        """
        If the FSM has been shutdown it ignores disconnection event.
        """
        client = build_protocol()
        desired = object()
        state = object()
        self.fsm.receive(_ClientConnected(client=client))
        self.fsm.receive(_StatusUpdate(configuration=desired, state=state))
        self.fsm.receive(ClusterStatusInputs.SHUTDOWN)
        self.fsm.receive(ClusterStatusInputs.CLIENT_DISCONNECTED)
        self.assertConvergenceLoopInputted([
            _ClientStatusUpdate(client=client, configuration=desired,
                                state=state),
            # This is caused by the shutdown... and the disconnect results
            # in no further messages:
            ConvergenceLoopInputs.STOP])

    def test_shutdown_fsm_ignores_cluster_status(self):
        """
        If the FSM has been shutdown it ignores cluster status update.
        """
        client = build_protocol()
        desired = object()
        state = object()
        self.fsm.receive(_ClientConnected(client=client))
        self.fsm.receive(ClusterStatusInputs.SHUTDOWN)
        self.fsm.receive(_StatusUpdate(configuration=desired, state=state))
        # We never send anything to agent operation FSM:
        self.assertConvergenceLoopInputted([])


class ConvergenceLoopFSMTests(SynchronousTestCase):
    """
    Tests for FSM created by ``build_convergence_loop_fsm``.
    """
    def test_new_stopped(self):
        """
        A newly created FSM is stopped.
        """

    def test_new_status_update_starts_discovery(self):
        """
        A stopped FSM that receives a status update starts discovery.
        """

    def test_new_status_update_stores_values(self):
        """
        A stopped FSM that receives a status update stores the client, desired
        configuration and cluster state.
        """

    def test_discovery_done(self):
        """
        A FSM doing discovery that gets a result starts applying calculated
        changes.
        """

    def test_discovery_status_update(self):
        """
        A FSM doing discovery that receives a status update stores the client,
        desired configuration and cluster state.
        """

    def test_discovery_stop(self):
        """
        A FSM doing discovery that receives a stop input stops when discovery
        finishes.
        """

    def test_discovery_stop_then_status_update(self):
        """
        A FSM doing discovery that receives a stop input and then a status
        update applies calculated changes (i.e. stop ends up being
        ignored).
        """

    def test_changes_done(self):
        """
        A FSM applying changes switches to discovery after changes are done.
        """

    def test_changes_status_update(self):
        """
        A FSM applying changes that receives a status update stores the client,
        desired configuration and cluster state.
        """

    def test_changes_stop(self):
        """
        A FSM applying changes that receives a stop input stops when changes
        finishes.
        """

    def test_changes_stop_then_status_update(self):
        """
        A FSM applyings changes that receives a stop input and then a status
        update continues on to discovery (i.e. stop is ignored).
        """
