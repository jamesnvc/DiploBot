#!/usr/bin/env python2.7

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

class Diplobot(object):

    def __init__(self, nationality, server='localhost', port=3000,
            aggressiveness=1, defensiveness=1):
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
        self.session_id = None

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

    def update_board(self, owners_dict):
        """Update the board to reflect the current game state.

        :owners_dict: Dictionary of {'Territory':
                          {'owner': [new owner], 'strength': [# armies there]}
        """
        for territory, info in owners_dict.iteritems():
            if territory in self.owned and info['owner'] != self.nationality:
                self.owned.remove(territory)
            elif info['owner'] == self.nationality:
                self.owned.add(territory)
            self.board.node[territory]['belongsnto'] = info['owner']
            self.board.node[territory]['strength'] = info['strength']

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

        Gives orders in the form of [('Ter1', 'move', 'Ter2'), ('Ter3',
        'support', 'Ter1')].

        :returns: A list of tuples giving the orders for the next turn.
        """
        orders = list()
        for ter in self.owned:
            possible = sorted(
                    [adj for adj in self.board.adj[ter].keys()] + [ter],
                    key=lambda n: self.board.node[n]['score'])
            # TODO: Should randomly choose among the few best
            # TODO: What type of order is issued?
            # TODO: When to hold?
            to = possible[min(int(abs(random.gauss(0, 2))), len(possible))]
            mtype = 'm'
            orders.append({
                'move': mtype,
                'from': ter,
                'to': to,
                'tag': '',
                'support': 0
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
                    key=lambda t: self.board.node[t]['score'])[0]
            to_reinforce.append(ter)
            self.board.node[ter]['strength'] += 1
            self.score_territories()
        return to_reinforce

    def server_msg(self, ws, msg):
        print "Got server msg: {}".format(msg)
        msg_type = msg.split(':')[0]
        if msg_type == '1':
            print "Got connect msg"
            msg = ':'.join(['5', '1', '',
                json.dumps({'name': 'user:login',
                    'args': [{'name': 'Diplobot'}, None]})])
            print "Sending msg {}".format(msg)
            ws.send(msg)
            return
        if msg_type == '2': # Heartbeat
            ws.send('2::')
            return
        if msg_type == '5':
            data = json.loads(msg.split(':')[-1])
            event = data['name']
            args = data['args'][0]
            if event == 'login':
                self.user_id = args['_id']
            return

    def server_err(self, ws, err):
        print "Got server err: {}".format(err)

    def server_close(self, ws):
        print "Connection closed"
        if self.restart:
            self.start()

    def server_connected(self, ws):
        """Connected to server.

        :ws: websocket object
        """
        print "Connection opened"

    def handshake(self):
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

