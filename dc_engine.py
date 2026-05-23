import os
import sys
import time
import subprocess
import numpy as np

def check_immediate_threat(board, player):
    # board: 2D numpy array (19x19)
    # player: 1 (X) or -1 (O)
    # Return (r, c, reason) if a critical move is found, else None
    size = board.shape[0]
    
    def check_win_if_placed(r, c, p):
        board[r, c] = p
        win = False
        dirs = [(0,1), (1,0), (1,1), (1,-1)]
        for dr, dc in dirs:
            count = 1
            nr, nc = r+dr, c+dc
            while 0 <= nr < size and 0 <= nc < size and board[nr, nc] == p:
                count += 1
                nr += dr
                nc += dc
            nr, nc = r-dr, c-dc
            while 0 <= nr < size and 0 <= nc < size and board[nr, nc] == p:
                count += 1
                nr -= dr
                nc -= dc
            if count >= 5:  # Bất kể luật chặn 2 đầu, cứ 5 quân là thắng
                win = True
                break
        board[r, c] = 0
        return win

    # 1. Tự thắng trước
    for r in range(size):
        for c in range(size):
            if board[r, c] == 0:
                if check_win_if_placed(r, c, player):
                    return (r, c, "TỰ THẮNG (5 quân)")

    # 2. Chặn địch thắng
    for r in range(size):
        for c in range(size):
            if board[r, c] == 0:
                if check_win_if_placed(r, c, -player):
                    return (r, c, "CHẶN ĐỊCH THẮNG (4 quân hở)")
                    
    return None

class DCEngine:
    def __init__(self, rule_type=3, vcf_time=3.0, vct_time=5.0, mcts_simulations=400):
        self.rule_type = rule_type
        self.mcts_simulations = mcts_simulations
        self.model_loaded = False
        self.process = None
        self.board_size = 19
        
        # Hỗ trợ mang Bot sang máy khác: Tìm thư mục 'engine' nằm ngay cạnh Bot
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        engine_dir = os.path.join(base_dir, "engine")
        
        # Thử tìm lùi ra ngoài (dành cho lúc chạy code python thuần)
        if not os.path.exists(engine_dir):
            alt_engine = os.path.join(os.path.dirname(base_dir), "engine")
            if os.path.exists(alt_engine):
                engine_dir = alt_engine
            else:
                fallback_engine = r"E:\CODE\game caro\KataGomo20250206.CompatRTX50\KataGomo20250206\engine"
                if os.path.exists(fallback_engine):
                    engine_dir = fallback_engine
                    
        self.exe_path = ""
        possible_engines = [
            "gom20x_opencl.exe",
            "gom20x_trt.exe",
            "caro20x_opencl.exe",
            "caro20x_trt.exe",
            "gom15x_opencl.exe",
            "gom15x_trt.exe"
        ]
        
        if os.path.exists(engine_dir):
            for eng in possible_engines:
                test_path = os.path.join(engine_dir, eng)
                if os.path.exists(test_path):
                    self.exe_path = test_path
                    break
                    
        if not self.exe_path or not os.path.exists(self.exe_path):
            print(f"❌ KHÔNG TÌM THẤY file engine (Bộ não C++)! Đảm bảo thư mục 'engine' (chứa gom20x_opencl.exe hoặc caro20x_opencl.exe) nằm CÙNG CHỖ với file Bot.")
        
    def load_model(self, model_path):
        if not os.path.exists(self.exe_path):
            print("❌ BỎ QUA NẠP MODEL: Không có file engine C++.")
            self.model_loaded = False
            return False

        # Trích xuất tên file engine để in log cho rõ ràng
        engine_name = os.path.basename(self.exe_path)
        print(f"🤖 Đang khởi động {engine_name} với model: {model_path} ...")
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gtp.cfg")
        
        cmd = [
            self.exe_path,
            "gtp",
            "-model", model_path,
            "-config", cfg_path
        ]
        
        # Phải chạy exe trong chính thư mục chứa nó để không bị lỗi thiếu DLL (zlib, opencl...)
        engine_dir = os.path.dirname(self.exe_path)
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore',
                bufsize=1,
                cwd=engine_dir,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.model_loaded = True
        except Exception as e:
            print(f"❌ Lỗi khi gọi subprocess Popen: {e}")
            self.model_loaded = False
            return False
        self.latest_winrate = ""
        self.latest_pv = ""
        self.engine_move_history = []
        
        # Bắt đầu luồng đọc stderr để lấy Winrate và PV, đồng thời chống kẹt buffer
        self.engine_error_log = []
        import threading
        def _read_stderr():
            while self.process and self.process.poll() is None:
                try:
                    line = self.process.stderr.readline()
                    if not line: break
                    if "winrate" in line:
                        self.latest_winrate = line.strip()
                    elif line.startswith("PV:"):
                        self.latest_pv = line.strip()
                    else:
                        # Lưu lại các dòng không phải winrate/PV để debug khi crash
                        self.engine_error_log.append(line.strip())
                        if len(self.engine_error_log) > 10:
                            self.engine_error_log.pop(0)
                except Exception as e:
                    print(f"Luồng đọc stderr bị lỗi (cần báo Coder): {e}")
                    break
        self.stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        self.stderr_thread.start()
        
        # Đợi 1 chút xem nó có crash ngay lúc nạp model không
        time.sleep(1)
        if self.process.poll() is not None:
            # Lấy nốt log còn sót lại
            err = self.process.stderr.read()
            if err:
                self.engine_error_log.append(err.strip())
            
            full_err = "\\n".join(self.engine_error_log)
            print(f"❌ Kểt nối DC_bot thất bại! Mã lỗi: {self.process.returncode}")
            print(f"Chi tiết lỗi từ DC_bot: {full_err}")
            self.model_loaded = False
            return False
            
        # Thiết lập cơ bản cho bàn cờ VnCaro
        self.send_command(f"boardsize {self.board_size}")
        self.send_command("clear_board")
        # Thử set luật, nếu engine cũ không hỗ trợ thì kệ nó
        self.send_command("kata-set-rules VNCARO")
        print("✅ DC_bot đã sẵn sàng chiến đấu!")
        return True
        
    def send_command(self, cmd):
        if not self.process: return ""
        self.process.stdin.write(cmd + "\n")
        self.process.stdin.flush()
        
        output = ""
        while True:
            line = self.process.stdout.readline()
            if line.strip() == "":
                break
            output += line
        return output.strip()
        
    def coord_to_gtp(self, r, c):
        # r: 0->18 (0 là dòng trên cùng), c: 0->18
        # Cột GTP: A-T (bỏ qua I)
        cols = "ABCDEFGHJKLMNOPQRST"
        col_str = cols[c]
        row_str = str(self.board_size - r)
        return col_str + row_str
        
    def gtp_to_coord(self, gtp_str):
        if gtp_str.upper() == "PASS" or gtp_str.upper() == "RESIGN":
            return -1, -1
        cols = "ABCDEFGHJKLMNOPQRST"
        col_char = gtp_str[0].upper()
        row_str = gtp_str[1:]
        try:
            c = cols.index(col_char)
            r = self.board_size - int(row_str)
            return r, c
        except:
            return -1, -1
        
    def get_move(self, game, player, mcts_time_limit=10.0):
        if not self.model_loaded:
            return None, {"method": "ERROR", "detail": "Chưa nạp model DC_bot!"}
            
        # [HEURISTIC] Ép buộc nhận diện 4 con hở hoặc tự thắng
        threat_move = check_immediate_threat(game.board, player)
        if threat_move is not None:
            r, c, reason = threat_move
            # Push history into DC_bot so it stays in sync
            color = "B" if player == 1 else "W"
            gtp_color = "black" if color == "B" else "white"
            gtp_coord = self.coord_to_gtp(r, c)
            
            # Sync any missed moves first
            current_turn = 1
            for i, m in enumerate(game.move_history):
                if len(m) == 3:
                    rm, cm, p = m
                    current_turn = p
                else:
                    rm, cm = m[:2]
                    
                if i >= len(self.engine_move_history):
                    m_color = "B" if current_turn == 1 else "W"
                    m_gtp_color = "black" if m_color == "B" else "white"
                    m_gtp_coord = self.coord_to_gtp(rm, cm)
                    self.send_command(f"play {m_gtp_color} {m_gtp_coord}")
                    self.engine_move_history.append(m)
                current_turn = -current_turn
                    
            self.send_command(f"play {gtp_color} {gtp_coord}")
            self.engine_move_history.append((r, c, player))
            
            action = r * self.board_size + c
            return action, {"method": "Heuristic", "detail": f"Ép nhận diện: {reason}"}
            
        # Check if history is continuous
        is_continuous = False
        if len(game.move_history) >= len(self.engine_move_history):
            # Compare up to the length of engine_move_history
            match = True
            for i in range(len(self.engine_move_history)):
                m1 = game.move_history[i]
                m2 = self.engine_move_history[i]
                if m1[0] != m2[0] or m1[1] != m2[1]:
                    match = False
                    break
            if match:
                is_continuous = True
                
        if not is_continuous or len(game.move_history) == 0:
            self.send_command("clear_board")
            self.engine_move_history = []
            
        self.send_command(f"kata-set-param maxVisits={self.mcts_simulations}")
        
        current_turn = 1
        for i, m in enumerate(game.move_history):
            if len(m) == 3:
                r, c, p = m
                current_turn = p
            else:
                r, c = m[:2]
                
            if i >= len(self.engine_move_history):
                color = "B" if current_turn == 1 else "W"
                self.send_command(f"play {color} {self.coord_to_gtp(r, c)}")
                
            if len(m) < 3:
                current_turn = -current_turn
                
        # Update engine history to match the current board before genmove
        self.engine_move_history = list(game.move_history)
                
        # Nếu có ô trung lập (bị block)
        if hasattr(game, 'neutral_cells'):
            for (nr, nc) in game.neutral_cells:
                # Trong GTP cơ bản không có ô block, nhưng ta có thể lợi dụng DC_bot
                # Có thể phớt lờ vì luật VnCaro ít khi có ô bị block, hoặc gửi 1 lệnh đặc biệt.
                pass
                
        # Yêu cầu AI tính toán nước tiếp theo
        bot_color = "B" if player == 1 else "W"
        
        start_t = time.time()
        res = self.send_command(f"genmove {bot_color}")
        elapsed = time.time() - start_t
        
        # Đợi luồng đọc stderr bắt kịp log cuối cùng (tránh race condition)
        time.sleep(0.05)
        
        if res.startswith("="):
            gtp_move = res[1:].strip()
            if gtp_move.lower() not in ["resign", "pass"]:
                r, c = self.gtp_to_coord(gtp_move)
                # genmove internally plays the move in DC_bot, so we must add it to our tracking history
                self.engine_move_history.append((r, c, player))
                
                action = r * self.board_size + c
            else:
                # Nếu Bot đầu hàng hoặc bỏ lượt, bắt nó đánh đại 1 ô trống (Cờ Caro không có bỏ lượt)
                action = None
                for fallback_r in range(self.board_size):
                    for fallback_c in range(self.board_size):
                        if game.board[fallback_r, fallback_c] == 0:
                            self.engine_move_history.append((fallback_r, fallback_c, player))
                            action = fallback_r * self.board_size + fallback_c
                            break
                    if action is not None:
                        break
                
                if action is None:
                    return None, {"method": "ERROR", "detail": "Hết ô trống trên bàn cờ"}
                gtp_move = "PASS/RESIGN (Tự chọn ô trống)"
                
            # Format Tỉ lệ Thắng & Tương lai
            wr_text = ""
            winrate_val = 0.0
            if self.latest_winrate:
                parts = self.latest_winrate.split()
                for i, p in enumerate(parts):
                    if p == "winrate" and i+1 < len(parts):
                        try:
                            winrate_val = float(parts[i+1])
                            wr_text = f" | Tỉ lệ Thắng: {winrate_val*100:.2f}%"
                        except:
                            wr_text = f" | Tỉ lệ Thắng: {parts[i+1]}"
                        break
                        
            pv_text = ""
            if self.latest_winrate and " pv " in self.latest_winrate:
                try:
                    pv_str = self.latest_winrate.split(" pv ")[1]
                    pv_moves = pv_str.split()
                    # Lấy 15 nước tương lai
                    if len(pv_moves) > 15: pv_moves = pv_moves[:15]
                    
                    # Chỉ hiện khi winrate > 90% (Sửa theo yêu cầu dễ nhìn thấy hơn)
                    if winrate_val > 0.90 and pv_moves:
                        pv_text = f"\n      Tương lai (Win {winrate_val*100:.1f}%): {' -> '.join(pv_moves)}"
                except:
                    pass
            
            return action, {
                "method": "DC MCTS", 
                "detail": f"Time: {elapsed:.2f}s{wr_text} | Nước: {gtp_move}{pv_text}"
            }
                
        return None, {"method": "ERROR", "detail": f"DC_bot trả về lỗi: {res}"}
