#!/usr/bin/env python2.7

import json
import networkx as nx

class Diplobot(object):

    def __init__(self, nationality):
        self.nationality = nationality
        self.supply_centers = list()
        self.board = self.default_game_world()

    def default_game_world(self):
        territories = json.load(open('board.js'))
        board = nx.Graph()
        for territory, info in territories.iteritems():
            board.add_node(territory, fullname=info['fullname'],
                    supply=info['supply'], belongsto=info['belongsto'],
                    score=0)
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
            self.board.node[territory]['belongsnto'] = info['owner']
            self.board.node[territory]['strength'] = info['strength']

    def score_territories(self):
        """Compute the scores for each node territory on the board
        """
        for center in self.supply_centers:
            info = self.board.node[center]
            if info['belongsto'] == self.nationality:
                info['score'] = sum(ter['strength'] for ter
                        in self.board.adj(center)
                        if ter['belongsto'] != self.nationality)
            else:
                info['score'] = info['strength']

