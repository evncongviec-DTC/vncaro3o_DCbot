import numpy as np
import random
import math
import sys
import os
from neutral_patterns import NEUTRAL_PATTERNS
BOARD_SIZE = 19
ACTION_SIZE = BOARD_SIZE * BOARD_SIZE
class CaroGame:
    def __init__(self, rule_type=3, *args, **kwargs):
        self.rule_type = rule_type
        self.board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.int8)
        self.neutral_cells = []
        self.move_history = [] 
        self.attack_weight = 1.2   
        self.defense_weight = 1.1  
        self.generate_neutral_cells()
    def generate_neutral_cells(self):
        pts = random.choice(NEUTRAL_PATTERNS)
        for r, c in pts:
            self.board[r, c] = 2 
            self.neutral_cells.append((r, c))
    def get_valid_moves(self, current_player_is_X):
        valid_moves = np.zeros(ACTION_SIZE, dtype=np.float32)
        total_pieces = int(np.sum((self.board == 1) | (self.board == -1)))
        if total_pieces == 0:
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    if self.board[r, c] == 0:
                        is_adj = False
                        has_good_runway = False
                        for nr in range(BOARD_SIZE):
                            for nc in range(BOARD_SIZE):
                                if self.board[nr, nc] == 2:
                                    dr, dc = r - nr, c - nc
                                    if max(abs(dr), abs(dc)) == 1:
                                        is_adj = True
                                        count = 0
                                        cr, cc = r + dr, c + dc
                                        while 0 <= cr < BOARD_SIZE and 0 <= cc < BOARD_SIZE and self.board[cr, cc] == 0:
                                            count += 1
                                            cr += dr
                                            cc += dc
                                        if count >= 5:
                                            has_good_runway = True
                        if is_adj and has_good_runway:
                            valid_moves[r * BOARD_SIZE + c] = 1
            if np.sum(valid_moves) == 0:
                for r in range(BOARD_SIZE):
                    for c in range(BOARD_SIZE):
                        if self.board[r, c] == 0:
                            for nr in range(BOARD_SIZE):
                                for nc in range(BOARD_SIZE):
                                    if self.board[nr, nc] == 2 and max(abs(r - nr), abs(c - nc)) == 1:
                                        valid_moves[r * BOARD_SIZE + c] = 1
            return valid_moves
        if current_player_is_X and total_pieces == 2:
            x1_r, x1_c = None, None
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    if self.board[r, c] == 1:
                        x1_r, x1_c = r, c
                        break
                if x1_r is not None: break
            if x1_r is not None:
                for r in range(BOARD_SIZE):
                    for c in range(BOARD_SIZE):
                        if self.board[r, c] == 0:
                            dist = max(abs(r - x1_r), abs(c - x1_c))
                            if dist == 4 and 3 <= r < BOARD_SIZE - 3 and 3 <= c < BOARD_SIZE - 3:
                                valid_moves[r * BOARD_SIZE + c] = 1
                if np.sum(valid_moves) > 0:
                    return valid_moves
        current_player = 1 if current_player_is_X else -1
        occupied = (self.board != 0)
        proximity_mask = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=bool)
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if occupied[r, c]:
                    rmin, rmax = max(0, r-4), min(BOARD_SIZE, r+5)
                    cmin, cmax = max(0, c-4), min(BOARD_SIZE, c+5)
                    proximity_mask[rmin:rmax, cmin:cmax] = True
        win_moves = np.zeros(ACTION_SIZE, dtype=np.float32)
        has_win = False
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if self.board[r, c] == 0 and proximity_mask[r, c]:
                    self.board[r, c] = current_player
                    if self.check_win(r * BOARD_SIZE + c, current_player):
                        win_moves[r * BOARD_SIZE + c] = 1
                        has_win = True
                    self.board[r, c] = 0
        if has_win:
            self._cached_scores = win_moves * 100000
            return win_moves
        block_moves = np.zeros(ACTION_SIZE, dtype=np.float32)
        has_block = False
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if self.board[r, c] == 0 and proximity_mask[r, c]:
                    self.board[r, c] = -current_player
                    if self.check_win(r * BOARD_SIZE + c, -current_player):
                        block_moves[r * BOARD_SIZE + c] = 1
                        has_block = True
                    self.board[r, c] = 0
        if has_block:
            for idx in range(ACTION_SIZE):
                if block_moves[idx] > 0:
                    br, bc = idx // BOARD_SIZE, idx % BOARD_SIZE
                    bonus = self.evaluate_cell(br, bc, current_player)
                    block_moves[idx] = 100000 + bonus
            self._cached_scores = block_moves
            return (block_moves > 0).astype(np.float32)
        scores = np.zeros(ACTION_SIZE, dtype=np.float32)
        total_pieces = int(np.sum(self.board != 0))
        board_quarter = (BOARD_SIZE * BOARD_SIZE) // 4
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if self.board[r, c] != 0 or not proximity_mask[r, c]:
                    continue
                dist_to_edge = min(r, c, BOARD_SIZE - 1 - r, BOARD_SIZE - 1 - c)
                if dist_to_edge <= 1:
                    if total_pieces < board_quarter:
                        has_chain = False
                        for dr2 in [-1, 0, 1]:
                            for dc2 in [-1, 0, 1]:
                                if dr2 == 0 and dc2 == 0: continue
                                nr2, nc2 = r + dr2, c + dc2
                                if 0 <= nr2 < BOARD_SIZE and 0 <= nc2 < BOARD_SIZE:
                                    nd = min(nr2, nc2, BOARD_SIZE-1-nr2, BOARD_SIZE-1-nc2)
                                    if nd > dist_to_edge and self.board[nr2, nc2] != 0:
                                        has_chain = True; break
                            if has_chain: break
                        if not has_chain: continue
                    board_two_thirds = (BOARD_SIZE * BOARD_SIZE) * 2 // 3
                    if total_pieces < board_two_thirds:
                        only_edge_neighbors = True
                        for dr2 in [-1, 0, 1]:
                            for dc2 in [-1, 0, 1]:
                                if dr2 == 0 and dc2 == 0: continue
                                nr2, nc2 = r + dr2, c + dc2
                                if 0 <= nr2 < BOARD_SIZE and 0 <= nc2 < BOARD_SIZE:
                                    if self.board[nr2, nc2] != 0:
                                        nd2 = min(nr2, nc2, BOARD_SIZE-1-nr2, BOARD_SIZE-1-nc2)
                                        if nd2 > 1:
                                            only_edge_neighbors = False; break
                            if not only_edge_neighbors: break
                        if only_edge_neighbors: continue
                is_edge = (dist_to_edge <= 2)
                if dist_to_edge == 2:
                    has_chain_inward = False
                    for dr2 in [-1, 0, 1]:
                        for dc2 in [-1, 0, 1]:
                            if dr2 == 0 and dc2 == 0: continue
                            nr2, nc2 = r + dr2, c + dc2
                            if 0 <= nr2 < BOARD_SIZE and 0 <= nc2 < BOARD_SIZE:
                                neighbor_dist = min(nr2, nc2, BOARD_SIZE-1-nr2, BOARD_SIZE-1-nc2)
                                if neighbor_dist > dist_to_edge and self.board[nr2, nc2] != 0:
                                    has_chain_inward = True; break
                        if has_chain_inward: break
                    if not has_chain_inward: continue
                my_score = self.evaluate_cell(r, c, current_player)
                opp_score = self.evaluate_cell(r, c, -current_player)
                dist_center = abs(r - 9) + abs(c - 9)
                pos_bonus = max(0, 30 - dist_center * 3)
                if is_edge: pos_bonus = -50
                cell_score = (my_score * self.attack_weight) + (opp_score * self.defense_weight) + pos_bonus
                scores[r * BOARD_SIZE + c] = max(cell_score, 1)
        if np.sum(scores) > 0:
            max_score = np.max(scores)
            if max_score >= 100000:
                scores[scores < 100000] = 0
            elif max_score >= 50000:
                scores[scores < 50000] = 0
            elif max_score >= 30000:
                scores[scores < 30000] = 0
            elif max_score >= 3000:
                scores[scores < 3000] = 0
            else:
                scores[scores < max_score * 0.5] = 0
            self._cached_scores = scores.copy()
            valid_moves = (scores > 0).astype(np.float32)
            return valid_moves
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if self.board[r, c] == 0:
                    valid_moves[r * BOARD_SIZE + c] = 1
        return valid_moves
    def get_heuristic_policy(self, current_player_is_X):
        """Trả về policy prior dựa trên điểm heuristic (dùng cho MCTS)"""
        current_player = 1 if current_player_is_X else -1
        scores = np.zeros(ACTION_SIZE, dtype=np.float32)
        occupied = (self.board != 0)
        proximity_mask = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=bool)
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if occupied[r, c]:
                    rmin, rmax = max(0, r-6), min(BOARD_SIZE, r+7)
                    cmin, cmax = max(0, c-6), min(BOARD_SIZE, c+7)
                    proximity_mask[rmin:rmax, cmin:cmax] = True
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if self.board[r, c] != 0 or not proximity_mask[r, c]:
                    continue
                dist_to_edge = min(r, c, BOARD_SIZE - 1 - r, BOARD_SIZE - 1 - c)
                total_pieces = int(np.sum(self.board != 0))
                board_quarter = (BOARD_SIZE * BOARD_SIZE) // 4
                if dist_to_edge <= 1:
                    if total_pieces < board_quarter:
                        has_chain = False
                        for dr2 in [-1, 0, 1]:
                            for dc2 in [-1, 0, 1]:
                                if dr2 == 0 and dc2 == 0: continue
                                nr2, nc2 = r + dr2, c + dc2
                                if 0 <= nr2 < BOARD_SIZE and 0 <= nc2 < BOARD_SIZE:
                                    nd = min(nr2, nc2, BOARD_SIZE-1-nr2, BOARD_SIZE-1-nc2)
                                    if nd > dist_to_edge and self.board[nr2, nc2] != 0:
                                        has_chain = True; break
                            if has_chain: break
                        if not has_chain: continue
                    board_two_thirds = (BOARD_SIZE * BOARD_SIZE) * 2 // 3
                    if total_pieces < board_two_thirds:
                        only_edge_neighbors = True
                        for dr2 in [-1, 0, 1]:
                            for dc2 in [-1, 0, 1]:
                                if dr2 == 0 and dc2 == 0: continue
                                nr2, nc2 = r + dr2, c + dc2
                                if 0 <= nr2 < BOARD_SIZE and 0 <= nc2 < BOARD_SIZE:
                                    if self.board[nr2, nc2] != 0:
                                        nd = min(nr2, nc2, BOARD_SIZE-1-nr2, BOARD_SIZE-1-nc2)
                                        if nd > 1:
                                            only_edge_neighbors = False; break
                            if not only_edge_neighbors: break
                        if only_edge_neighbors: continue
                is_edge = (dist_to_edge <= 2)
                if dist_to_edge == 2:
                    has_chain_inward = False
                    for dr2 in [-1, 0, 1]:
                        for dc2 in [-1, 0, 1]:
                            if dr2 == 0 and dc2 == 0: continue
                            nr2, nc2 = r + dr2, c + dc2
                            if 0 <= nr2 < BOARD_SIZE and 0 <= nc2 < BOARD_SIZE:
                                neighbor_dist = min(nr2, nc2, BOARD_SIZE-1-nr2, BOARD_SIZE-1-nc2)
                                if neighbor_dist > dist_to_edge and self.board[nr2, nc2] != 0:
                                    has_chain_inward = True; break
                        if has_chain_inward: break
                    if not has_chain_inward: continue
                my_score = self.evaluate_cell(r, c, current_player)
                opp_score = self.evaluate_cell(r, c, -current_player) * 1.1
                dist_center = abs(r - 9) + abs(c - 9)
                pos_bonus = max(0, 30 - dist_center * 3)
                if is_edge: pos_bonus = -50
                scores[r * BOARD_SIZE + c] = max(my_score + opp_score + pos_bonus, 1)
        max_score = np.max(scores)
        if max_score >= 100000:
            scores[scores < 100000] = 0
        elif max_score >= 50000:
            scores[scores < 50000] = 0
        elif max_score >= 30000:
            scores[scores < 30000] = 0
        elif max_score >= 3000:
            scores[scores < 3000] = 0
        elif max_score > 5000:
            scores[scores < max_score * 0.2] = 0
        total = np.sum(scores)
        if total > 0:
            scores = np.power(scores, 1.5)
            total = np.sum(scores)
            return scores / total
        return None
    def evaluate_cell(self, r, c, player):
        """Chấm điểm chiến thuật cho 1 ô trống theo góc nhìn của player"""
        self.board[r, c] = player
        total_score = 0
        four_count = 0
        open3_count = 0
        dirs = [(0,1), (1,0), (1,1), (1,-1)]
        for dr, dc in dirs:
            line_score, pattern_type = self.score_direction(r, c, dr, dc, player)
            total_score += line_score
            if pattern_type in ('C4', 'B4'):
                four_count += 1
            elif pattern_type == 'O3':
                open3_count += 1
            elif pattern_type == 'O4':
                four_count += 2  
        if four_count >= 2:
            total_score += 60000  
        elif four_count >= 1 and open3_count >= 1:
            total_score += 40000  
        elif open3_count >= 2:
            total_score += 30000  
        self.board[r, c] = 0
        return total_score
    def score_direction(self, r, c, dr, dc, player):
        """Quét 1 hướng qua ô (r,c), trả về (điểm, loại_pattern)"""
        count_pos = 0
        gap_pos = 0
        after_gap_pos = 0
        nr, nc = r+dr, c+dc
        while 0<=nr<BOARD_SIZE and 0<=nc<BOARD_SIZE and self.board[nr,nc] == player:
            count_pos += 1
            nr, nc = nr+dr, nc+dc
        if 0<=nr<BOARD_SIZE and 0<=nc<BOARD_SIZE and self.board[nr,nc] == 0:
            gnr, gnc = nr+dr, nc+dc
            while 0<=gnr<BOARD_SIZE and 0<=gnc<BOARD_SIZE and self.board[gnr,gnc] == player:
                after_gap_pos += 1
                gnr, gnc = gnr+dr, gnc+dc
            if after_gap_pos > 0:
                gap_pos = 1
        end1_empty = (0<=nr<BOARD_SIZE and 0<=nc<BOARD_SIZE and self.board[nr,nc] == 0)
        count_neg = 0
        gap_neg = 0
        after_gap_neg = 0
        nr, nc = r-dr, c-dc
        while 0<=nr<BOARD_SIZE and 0<=nc<BOARD_SIZE and self.board[nr,nc] == player:
            count_neg += 1
            nr, nc = nr-dr, nc-dc
        if 0<=nr<BOARD_SIZE and 0<=nc<BOARD_SIZE and self.board[nr,nc] == 0:
            gnr, gnc = nr-dr, nc-dc
            while 0<=gnr<BOARD_SIZE and 0<=gnc<BOARD_SIZE and self.board[gnr,gnc] == player:
                after_gap_neg += 1
                gnr, gnc = gnr-dr, gnc-dc
            if after_gap_neg > 0:
                gap_neg = 1
        end2_empty = (0<=nr<BOARD_SIZE and 0<=nc<BOARD_SIZE and self.board[nr,nc] == 0)
        consecutive = 1 + count_pos + count_neg  
        total_with_gap = consecutive + (after_gap_pos if gap_pos else 0) + (after_gap_neg if gap_neg else 0)
        room = consecutive
        tr, tc = r + dr * (count_pos + 1), c + dc * (count_pos + 1)
        while 0 <= tr < BOARD_SIZE and 0 <= tc < BOARD_SIZE and self.board[tr, tc] in (0, player):
            room += 1
            tr, tc = tr + dr, tc + dc
        tr, tc = r - dr * (count_neg + 1), c - dc * (count_neg + 1)
        while 0 <= tr < BOARD_SIZE and 0 <= tc < BOARD_SIZE and self.board[tr, tc] in (0, player):
            room += 1
            tr, tc = tr - dr, tc - dc
        if room < 5:
            return 0, 'DEAD'
        room_multiplier = 1.0 + room * 0.01
        if consecutive >= 5:
            return 100000 * room_multiplier, 'WIN'
        if total_with_gap >= 5 and (gap_pos or gap_neg):
            return 100000 * room_multiplier, 'WIN'
        if consecutive == 4 and end1_empty and end2_empty:
            return 50000 * room_multiplier, 'O4'
        if consecutive == 4 and (end1_empty or end2_empty):
            return 5000 * room_multiplier, 'C4'
        if total_with_gap == 4 and (gap_pos or gap_neg):
            return 5000 * room_multiplier, 'B4'
        if consecutive == 3 and end1_empty and end2_empty:
            return 3000 * room_multiplier, 'O3'
        if total_with_gap == 3 and (gap_pos or gap_neg) and end1_empty and end2_empty:
            return 2000 * room_multiplier, 'B3'
        if consecutive == 3 and (end1_empty or end2_empty):
            return 500 * room_multiplier, 'C3'
        if consecutive == 2 and end1_empty and end2_empty:
            return 200 * room_multiplier, 'O2'
        if total_with_gap == 2 and (gap_pos or gap_neg) and end1_empty and end2_empty:
            return 100 * room_multiplier, 'B2'
        if consecutive == 2 and (end1_empty or end2_empty):
            return 50 * room_multiplier, 'C2'
        if end1_empty or end2_empty:
            return 10 * room_multiplier, 'S1'
        return 0, 'DEAD'
    def execute_move(self, action, current_player):
        r = action // BOARD_SIZE
        c = action % BOARD_SIZE
        self.board[r, c] = current_player
        self.move_history.append((r, c))
    def check_win(self, action, player):
        r = action // BOARD_SIZE
        c = action % BOARD_SIZE
        dirs = [(0,1), (1,0), (1,1), (1,-1)]
        for dr, dc in dirs:
            count = 1
            nr, nc = r+dr, c+dc
            while 0<=nr<BOARD_SIZE and 0<=nc<BOARD_SIZE and self.board[nr,nc] == player:
                count += 1
                nr, nc = nr+dr, nc+dc
            nr, nc = r-dr, c-dc
            while 0<=nr<BOARD_SIZE and 0<=nc<BOARD_SIZE and self.board[nr,nc] == player:
                count += 1
                nr, nc = nr-dr, nc-dc
            if count >= 5:
                return True
        return False
    def get_empty_cells(self, use_proximity=False):
        occupied = (self.board != 0)
        if not use_proximity or not np.any(occupied):
            return [r * BOARD_SIZE + c for r in range(BOARD_SIZE) for c in range(BOARD_SIZE) if self.board[r, c] == 0]
        mask = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=bool)
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if occupied[r, c]:
                    rmin, rmax = max(0, r-3), min(BOARD_SIZE, r+4)
                    cmin, cmax = max(0, c-3), min(BOARD_SIZE, c+4)
                    mask[rmin:rmax, cmin:cmax] = True
        return [r * BOARD_SIZE + c for r in range(BOARD_SIZE) for c in range(BOARD_SIZE) if self.board[r, c] == 0 and mask[r, c]]
    def count_line(self, r, c, dr, dc, player):
        count = 1
        runway = 1
        end1_open = False
        end2_open = False
        nr, nc = r+dr, c+dc
        while 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == player:
            count += 1
            runway += 1
            nr, nc = nr+dr, nc+dc
        if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == 0:
            end1_open = True
            tnr, tnc = nr, nc
            while 0 <= tnr < BOARD_SIZE and 0 <= tnc < BOARD_SIZE and self.board[tnr,tnc] in (0, player):
                runway += 1
                tnr, tnc = tnr+dr, tnc+dc
        nr, nc = r-dr, c-dc
        while 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == player:
            count += 1
            runway += 1
            nr, nc = nr-dr, nc-dc
        if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == 0:
            end2_open = True
            tnr, tnc = nr, nc
            while 0 <= tnr < BOARD_SIZE and 0 <= tnc < BOARD_SIZE and self.board[tnr,tnc] in (0, player):
                runway += 1
                tnr, tnc = tnr-dr, tnc-dc
        return count, end1_open, end2_open, runway
    def find_winning_moves(self, player):
        moves = []
        for action in self.get_empty_cells(use_proximity=True):
            r, c = action // BOARD_SIZE, action % BOARD_SIZE
            self.board[r, c] = player
            if self.check_win(action, player):
                moves.append(action)
            self.board[r, c] = 0
        return moves
    def find_fours(self, player):
        fours = []
        dirs = [(0,1), (1,0), (1,1), (1,-1)]
        for action in self.get_empty_cells(use_proximity=True):
            r, c = action // BOARD_SIZE, action % BOARD_SIZE
            self.board[r, c] = player
            for dr, dc in dirs:
                count, e1, e2, run = self.count_line(r, c, dr, dc, player)
                if count >= 4 and run >= 5:
                    if count == 4 and (e1 or e2):
                        defs = []
                        if e1:
                            nr, nc = r+dr, c+dc
                            while 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == player:
                                nr, nc = nr+dr, nc+dc
                            if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == 0:
                                defs.append(nr*BOARD_SIZE + nc)
                        if e2:
                            nr, nc = r-dr, c-dc
                            while 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == player:
                                nr, nc = nr-dr, nc-dc
                            if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == 0:
                                defs.append(nr*BOARD_SIZE + nc)
                        if defs:
                            four_type = 'open4' if (e1 and e2) else 'closed4'
                            fours.append((action, four_type, defs))
            self.board[r, c] = 0
        return fours
    def _is_three(self, count, end1_open, end2_open):
        return count == 3 and end1_open and end2_open
    def find_open_threes(self, player):
        threes = []
        dirs = [(0,1), (1,0), (1,1), (1,-1)]
        for action in self.get_empty_cells(use_proximity=True):
            r, c = action // BOARD_SIZE, action % BOARD_SIZE
            self.board[r, c] = player
            for dr, dc in dirs:
                count, e1, e2, run = self.count_line(r, c, dr, dc, player)
                if self._is_three(count, e1, e2) and run > 5:
                    defs = []
                    nr, nc = r+dr, c+dc
                    while 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == player:
                        nr, nc = nr+dr, nc+dc
                    if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == 0:
                        defs.append(nr*BOARD_SIZE + nc)
                    nr, nc = r-dr, c-dc
                    while 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == player:
                        nr, nc = nr-dr, nc-dc
                    if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and self.board[nr,nc] == 0:
                        defs.append(nr*BOARD_SIZE + nc)
                    if defs:
                        threes.append((action, defs))
            self.board[r, c] = 0
        return threes
    def action_to_str(self, action):
        r = action // BOARD_SIZE
        c = action % BOARD_SIZE
        return f"({r},{c})"
    def print_board(self, last_move=None):
        symbols = {0: '.', 1: 'X', -1: 'O', 2: '▣'}
        print(f"\n  📋 Luật: {self.get_rule_name()}")
        header = "    " + " ".join([f"{i:2d}" for i in range(BOARD_SIZE)])
        print(header)
        print("   +" + "---" * BOARD_SIZE + "+")
        for r in range(BOARD_SIZE):
            row_str = f"{r:2d} |"
            for c in range(BOARD_SIZE):
                val = self.board[r, c]
                sym = symbols.get(val, '?')
                if last_move is not None and (r, c) == last_move:
                    row_str += f"[{sym}]"
                else:
                    row_str += f" {sym} "
            row_str += "|"
            print(row_str)
        print("   +" + "---" * BOARD_SIZE + "+")
        if self.neutral_cells:
            nc_str = ", ".join([f"({r},{c})" for r, c in self.neutral_cells])
            print(f"   ▣ Ô trung lập: {nc_str}")
        print(f"   X: Đi trước | O: Đi sau | Tổng nước: {len(self.move_history)}\n")
    def get_state_tensor(self, current_player):
        state = np.zeros((3, BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
        state[0] = (self.board == current_player).astype(np.float32)
        state[1] = (self.board == -current_player).astype(np.float32)
        state[2] = (self.board == 2).astype(np.float32)
        return state
    def clone(self):
        new_game = CaroGame(rule_type=self.rule_type)
        new_game.board = np.copy(self.board)
        new_game.move_history = list(self.move_history)
        new_game.neutral_cells = list(self.neutral_cells)
        return new_game
    def print_board(self):
        symbols = {0: '.', 1: 'X', -1: 'O', 2: '#'}
        header = "   " + " ".join([f"{i:2d}" for i in range(BOARD_SIZE)])
        print(header)
        for r in range(BOARD_SIZE):
            row_str = f"{r:2d} "
            for c in range(BOARD_SIZE):
                row_str += f" {symbols[self.board[r, c]]}" + " "
            print(row_str)
        print("(#: Ô trung lập, X: Đi trước, O: Đi sau)\n")
