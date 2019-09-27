import uuid
import json
from .room import Room
import logging

logger = logging.getLogger(__name__);

class Connection():
    ws = None
    hub = None
    user_id = None

    def __init__(self, hub, ws):
        self.ws = ws
        self.hub = hub
        self.subscriptions = {}
        self.allowed_rooms = []
        self.uuid = uuid.uuid4()

        # Nasty hack
        try:
            ws.connection = self
        except AttributeError:
            pass

    def handle_auth_success(self, data):
        user = data.get('user') or {}
        self.user_id = user.get('id')
        self.allowed_rooms = data.get('allowed_rooms', [])

        self.send({'allowed_rooms': self.allowed_rooms})

    def handle(self, message):
        if message == 'ping':
            self.send('pong')
            return

        m = json.loads(message)

        requestId = m.get('requestId', None)

        if m['type'] == 'subscribe':
            return self.handle_subscribe(m)

        if m['type'] == 'unsubscribe':
            return self.handle_unsubscribe(m)

        self.send({
            'requestId': requestId,
            'code': 'error',
            'message': 'message-type-not-allowed',
        })

    # If all keys match for a certain room,
    def is_room_allowed(self, room_dict):
        def room_matches(rd, ar):
            if len(rd.keys()) != len(ar.keys()):
                return False
            for ar_key in ar.keys():
                if ar_key not in rd:
                    return False
                if ar[ar_key] == '*':
                    continue
                if rd[ar_key] != ar[ar_key]:
                    return False

            return True

        for ar in self.allowed_rooms:
            if room_matches(room_dict, ar):
                return True

        return False

    def handle_subscribe(self, m):
        room_dict = m.get('room', None)
        room_hash = Room.hash_dict(room_dict)

        if not self.is_room_allowed(room_dict):
            self.send({
                'requestId': m['requestId'],
                'code': 'error',
                'message': 'room-not-found',
            })
            return

        sub = self.hub.subscribe(self, m, room_hash)
        self.subscriptions[m['requestId']] = sub
        self.send({
            'requestId': m['requestId'],
            'code': 'success',
        })

    def handle_unsubscribe(self, m):
        reqId = m['requestId']
        if reqId not in self.subscriptions:
            self.send({
                'requestId': m['requestId'],
                'code': 'error',
                'message': 'not-subscribed',
            })
            return

        sub = self.subscriptions[reqId]
        sub.stop()

        self.subscriptions.pop(reqId)
        self.send({
            'requestId': reqId,
            'code': 'success',
        })

    def unsubscribe_all(self):
        for room in [sub.room for sub in self.subscriptions.values()]:
            room.remove_connection(self)

        self.subscriptions = {}

    def send(self, message):
        if self.ws.closed:
            return
        import gevent
        def _send(ws, message):	
            ws.stream.handler.socket.settimeout(0.1)
            ws.send(json.dumps(message))
            ws.stream.handler.socket.settimeout(None)


        gevent.spawn(_send, self.ws, message)
