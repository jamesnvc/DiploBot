#!/usr/bin/env python2.7
"""Implementation of my Diplomacy bot, designed to play with the node Diplomacy
game at <https://github.com/rafd/Diplomacy> via websockets
"""

import Queue
import json
import networkx as nx
import websocket
import random
import requests

def id_gen(start=1):
    num = start
    while True:
        yield num
        num += 1

# TODO: Split apart into bot & server communication (which can have many bots)
class Diplobot(object):
    """Class representing an instance of the Diplomacy-playing bot."""

    def __init__(self, nationality, server='localhost', port=3000,
            aggressiveness=1, defensiveness=1):
        # NB: This gets overwritten when connecting to the server game
        self.nationality = nationality
        # Higher aggressiveness => more likely to attack vulnerable territories
        self.aggressiveness = aggressiveness
        # Higher defensiveness => more likely to defened threatened territories
        self.defensiveness = defensiveness
        self.server = server
        self.port = port
        self.supply_centers = list()
        self.owned = set()
        self.board = self.default_game_world()
        # State for server communication
        self.user_id = None
        self.player_id = None
        self.session_id = None
        self.game_id = None

    def default_game_world(self):
        """Create the default Diplomacy board.

        :returns: A nx.Graph representing the default Diplomacy board.
        """
        territories = json.load(open('board.js'))
        board = nx.Graph()
        for territory, info in territories.iteritems():
            if info['belongsto'] == self.nationality:
                self.owned.add(territory)
            board.add_node(territory, fullname=info['fullname'],
                    supply=info['supply'], belongsto=info['belongsto'],
                    score=0, strength=0)
            if info['supply'] == 1:
                self.supply_centers.append(territory)
        for territory, info in territories.iteritems():
            for adj in info['fleet_moves']:
                board.add_edge(territory, adj, type='fleet')
            for adj in info['army_moves']:
                board.add_edge(territory, adj, type='army')
        return board

    def extract_owners(self, units_list):
        """Process the units list from the server to a dict of owners for
        :update_board:.

        :units_list: List of units from the server
        :returns: Dict of owners suitable to be given to :update_board:.
        """
        utypes = {'a': 'army', 'f': 'fleet'}
        owners_dict = dict()
        for unit in units_list:
            if unit['province'] in owners_dict:
                owners_dict[unit['province']]['strength'] += 1
            else:
                owners_dict[unit['province']] = {
                        'belongsto': unit['owner'],
                        'type': utypes[unit['utype']],
                        'strength': 1}
        return owners_dict


    def update_board(self, owners_dict):
        """Update the board to reflect the current game state.

        :owners_dict: Dictionary of {'Territory':
                          {'belongsto': [new owner], 'strength': [# armies there]}
        """
        print "Updating board with new owners"
        for territory, info in owners_dict.iteritems():
            if territory in self.owned and info['belongsto'] != self.nationality:
                self.owned.remove(territory)
            elif info['belongsto'] == self.nationality:
                self.owned.add(territory)
            self.board.node[territory]['belongsto'] = info['belongsto']
            self.board.node[territory]['strength'] = info['strength']
            self.board.node[territory]['type'] = info['type']
        print "Board updated"

    def score_territories(self):
        """Compute the scores for each node territory on the board.

        Scoring algorithm:
        - Each supply center we own gets a score equal to the size of the largest
          adjacent force.
        - Each supply center we don't own gets a score equal to the size of the
          current owner's force.
        - Everything else starts at zero
        - Each coast gets a score equal to the its score times the sum of the
          scores of adjacent coasts weighted by a constant factor.
        - For each territory, calculate the strength of the attack we have on
          it versus the strength of the competetion for that territory.

        """
        for center in self.supply_centers:
            info = self.board.node[center]
            # TODO: Weight these scores by some internal "aggressiveness"
            # measure, to reflect how reckless we'll be?
            if info['belongsto'] == self.nationality:
                info['score'] = (sum(self.board.node[ter]['strength'] for ter
                        in self.board.adj[center].keys()
                        if self.board.node[ter]['belongsto'] != self.nationality)
                    - info['strength'])
            elif 'strength' in info:
                info['score'] = info['strength']
            else:
                info['score'] = 0
        search_queue = Queue.Queue()
        visited = set(self.supply_centers)
        weight = 0.2
        while not search_queue.empty():
            nd = search_queue.get()
            if nd in visited:
                continue
            visited.add(nd)
            self.board.node[nd]['score'] = weight * sum(ter['score'] for
                    ter in self.board.adj[nd].keys()
                    if ter in visited)
            adj = self.board.adj[nd].keys()
            for terr in adj:
                search_queue.put(terr)

    def next_move(self):
        """Determine the orders to give for the next turn.

        Gives orders in the form of [{'order': {
                                        'move': 'h'/'m'/'s',
                                        'from': territory issuing order,
                                        'to': destination
                                      },
                                      'owner': nationality
                                      'utype': 'a' or 'f'
                                      'province': territory issuing order
                                    }, ...]

        :returns: A list of dicts giving the orders for the next turn.
        """
        orders = list()
        for ter in self.owned:
            if self.board.node[ter]['strength'] > 0:
                possible = sorted(
                        [adj for adj in self.board.adj[ter].keys()] + [ter],
                        key=lambda n: self.board.node[n]['score'],
                        reverse=True)
                # TODO: Should randomly choose among the few best
                # TODO: What type of order is issued?
                # TODO: When to hold?
                to = possible[min(int(abs(random.gauss(0, 2))), len(possible))]
                mtype = 'm'
                to_node = self.board.node[to]
                if to == ter:
                    mtype = 'h'
                elif to_node['belongsto'] == self.nationality and to_node['strength'] != 0:
                    mtype = 's'
                orders.append({
                    'order': {
                        'move': mtype,
                        'from': ter,
                        'to': to
                    },
                    'owner': self.nationality,
                    'utype': self.board.node[ter]['type'][0],
                    'province': ter
                })
        return orders

    def next_secondary_move(self, units_available):
        """The next secondary move - i.e. where to place available
        reinforcements.

        :returns: A list of territories in which to place reinforcements.
        """
        to_reinforce = list()
        for i in xrange(units_available):
            ter = sorted(self.supply_centers,
                    key=lambda t: self.board.node[t]['score'],
                    reverse=True)[0]
            to_reinforce.append(ter)
            self.board.node[ter]['strength'] += 1
            self.score_territories()
        return to_reinforce

    def send_orders(self, orders):
        """Transmit the list of orders given to the server.

        :orders: A list of dicts in the form required by the server (see
                 :next_move: for details).
        """
        self.sock.send(':'.join(['5', '', '', json.dumps({
            'name': 'db',
            'args': [{'action': 'update',
                      'collection': 'player',
                      'data': {
                          'power': self.nationality,
                          'user': self.user_id,
                          '_id': self.player_id,
                          'orders': orders
                      }
                  }, None]
        })]))

    def server_msg(self, ws, msg):
        """Process communications recieved over the server socket.

        Since the server here is using socket.io, there is some processing of
        the websocket message which must be done - see
        <https://github.com/learnboost/socket.io-spec> for protocol details.

        :ws: The Websocket which the server is communicating on
        :msg: The message recieved from the server.
        """
        msg_type = msg.split(':')[0]
        if msg_type == '1':
            print "Got connect msg"
            msg = ':'.join(['5', '1', '',
                json.dumps({'name': 'user:login',
                    'args': [{'name': 'Diplobot'}, None]})])
            print "Logging in"
            ws.send(msg)
            return
        if msg_type == '2': # Heartbeat message from server
            ws.send('2::')
            return
        if msg_type == '5':
            data = json.loads(msg[(msg.find('{')):])
            event = data['name']
            print "Event {}".format(event)
            args = None
            if 'args' in data:
                args = data['args'][0]
            if event == 'login':
                print "Logged in as {}".format(args)
                self.user_id = args['_id']
            elif event == 'game:join':
                print "Joining game {} as {}".format(
                        args['gameId'], args['nationality'])
                self.nationality = args['nationality']
                self.game_id = args['gameId']
                ws.send(':'.join(['5', '', '', json.dumps({
                    'name': 'bot:joingame',
                    'args': [{
                        'gameId': self.game_id,
                        'botId': self.user_id,
                        'power': self.nationality
                    }]
                })]))
            elif event == 'bot:playerId':
                self.player_id = args['playerId']
            elif event == 'update:newgame':
                print "Game created"
            elif event == 'db:response':
                print "Got database response"
                print [game['_id'] for game in args]
            elif event == 'update:force':
                print "Force update to {} recieved".format(args['collection'])
                print 'Arg keys: {}'.format(args.keys())
                print 'Data keys: {}'.format(args['data'].keys())
                if args['collection'] == 'game':
                    print "Game state is now {}".format(args['data']['state'])
                    self.update_board(self.extract_owners(args['data']['units']))
                    print "Calculating next move"
                    if args['data']['state'] == 'primary':
                        orders = self.next_move()
                        print "Sending orders {}".format(orders)
                        self.send_orders(orders)
                    elif args['data']['state'] == 'secondary':
                        print "Secondary moves: {}".format(args)
                        # TODO: How many secondary moves do we have?
                        orders = self.next_secondary_move(1)
                        self.send_orders(orders)
                    else:
                        print "Unknown game state"
            return

    def server_err(self, ws, err):
        """Called when the websocket gives an error.

        Note that since the communication with the server uses socket.io over
        the websocket, this will only given transport-layer errors, application
        errors will come to :server_msg: in the socket.io method.

        :ws: Websocket
        :err: Error message from server
        """
        print "Got server err: {}".format(err)

    def server_close(self, ws):
        """Connection to server closed

        :ws: Websocket
        """
        print "Connection closed"
        if self.restart:
            self.start()

    def server_connected(self, ws):
        """Connected to server.

        :ws: websocket object
        """
        print "Connection opened"

    def handshake(self):
        """Make the initial handshake request to the server.

        This gives us the session id we will use to establish the websocket
        connection.
        """
        r = requests.post('http://{}:{}/socket.io/1'.format(
            self.server, self.port))
        self.session_id = r.text.split(':')[0]

    def start(self):
        """Start the bot running a game connecting with the given server
        """
        if self.session_id is None:
            self.handshake()
        self.sock = websocket.WebSocketApp(
                url = "ws://{}:{}/socket.io/1/websocket/{}".format(
                    self.server, self.port, self.session_id),
                on_message=self.server_msg,
                on_error=self.server_err,
                on_close=self.server_close)
        self.restart = self.session_id is None
        self.sock.on_open = self.server_connected
        self.sock.run_forever()

