import sys, os, io, time, datetime, pickle, threading
import numpy as np

# Ép UTF-8
try:
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except: pass

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QSpinBox, QRadioButton,
                             QGroupBox, QTextEdit, QDoubleSpinBox, QFileDialog, QCheckBox,
                             QSlider, QComboBox, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont, QTextCursor

# SpinBox không bị scroll/nhảy focus khi ấn mũi tên
class NoScrollSpinBox(QSpinBox):
    def wheelEvent(self, e): e.ignore()

class NoScrollDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, e): e.ignore()

from dc_engine import DCEngine
from game_rules import CaroGame

# =============================================
# Redirect print() từ HybridEngine vào GUI
# =============================================
class GUIStream:
    """Chuyển hướng mọi print() vào GUI log thay vì CMD."""
    def __init__(self, signal):
        self.signal = signal
        self.buffer = ""
    def write(self, text):
        if text.strip():
            self.signal.emit(text.rstrip())
    def flush(self): pass

# =============================================
# PONDERING THREAD - Nghĩ trước lúc chờ đối thủ
# =============================================
class PonderThread(threading.Thread):
    """Chạy engine.get_move() trong background."""
    def __init__(self, engine, game, player, mcts_time, simulations):
        super().__init__(daemon=True)
        self.engine = engine
        self.game = game
        self.player = player
        self.mcts_time = mcts_time
        self.simulations = simulations
        self.result_action = None
        self.result_info = None
        self.done = False

    def run(self):
        try:
            self.engine.mcts_simulations = self.simulations
            self.result_action, self.result_info = self.engine.get_move(
                self.game, self.player, mcts_time_limit=self.mcts_time)
        except Exception as e:
            self.result_action = None
            self.result_info = {'method': 'ERROR', 'detail': str(e)}
        self.done = True

# =============================================
# BOT THREAD - Luồng chính điều khiển Playwright
# =============================================
class BotThread(QThread):
    log_signal = pyqtSignal(str)
    side_detected = pyqtSignal(bool) # Mới: signal để cập nhật giao diện (True=X, False=O)
    history_signal = pyqtSignal(list, int) # Mới: signal để gửi lịch sử nước đi (move_history, board_size)
    stopped_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.active = False
        self.mode = "ai"
        self.auto_farm = False
        self.play_as_x = True
        self.delay_sec = 3.0
        self.mcts_time = 10.0
        self.simulations = 400
        self.is_running = True
        self.engine = None
        self.model_name = "nomodel"  # Tên model đang dùng
        self.neutral_cells = []
        self.move_history = []
        self.pkl_history = []
        self.last_mcts_policy = None  # MCTS policy distribution cho nước vừa đánh
        self.last_board = None
        self.phan_tich_ngam_thread = None  # Phân tích ngầm
        self.page = None
        self.pending_js = []  # JS commands từ GUI gửi sang Bot thread
        self.stats = {'X': 0, 'O': 0, 'Hòa': 0}  # Thống kê kết quả trận đấu
        self.custom_engine_path = None

    def log(self, text):
        self.log_signal.emit(text)

    # --- Lưu file Log & PKL ---
    def save_match_log(self, board, result, opp_elo=""):
        os.makedirs("logs", exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        elo_str = f"_{opp_elo}" if opp_elo else ""
        model_str = f"_{self.model_name}"

        # Xác định reward cho PKL
        if "thắng" in result.lower() or "thang" in result.lower() or "chiến thắng" in result.lower():
            winner_player = 1 if self.play_as_x else -1
        elif "thua" in result.lower() or "thất bại" in result.lower():
            winner_player = -1 if self.play_as_x else 1
        else:
            winner_player = 0

        # Xuất SGF gộp (để train)
        day_str = datetime.datetime.now().strftime('%Y%m%d')
        sgf_merged_fn = f"logs/vncaro_human_matches_{day_str}.sgf"
        try:
            with open(sgf_merged_fn, 'a', encoding='utf-8') as f:
                f.write("(;GM[1]FF[4]CA[UTF-8]AP[DC_bot_WebBot]SZ[19]\n")
                if winner_player == 1:
                    re_str = "B+Resign" if self.play_as_x else "W+Resign"
                elif winner_player == -1:
                    re_str = "W+Resign" if self.play_as_x else "B+Resign"
                else:
                    re_str = "0"
                f.write(f"PB[Black]PW[White]RE[{re_str}]DT[{datetime.datetime.now().strftime('%Y-%m-%d')}]\n")
                
                # Ghi các ô trung lập vào SGF (dùng AW/AB hoặc comment tùy ý, tạm dùng C để đánh dấu)
                if len(self.neutral_cells) > 0:
                    nc_strs = [f"({r},{c})" for r, c in self.neutral_cells]
                    f.write(f"C[NeutralCells:{';'.join(nc_strs)}]\n")
                
                # Ghi các nước đi
                for m in self.move_history:
                    # m = (r, c, player)
                    r, c = m[0], m[1]
                    p = m[2]
                    color = "B" if p == 1 else "W"
                    col_char = chr(97 + c)
                    row_char = chr(97 + r)
                    f.write(f";{color}[{col_char}{row_char}]")
                f.write(")\n")
            self.log(f"💾 Đã nối thêm 1 trận vào SGF tổng: {sgf_merged_fn}")
        except Exception as e:
            self.log(f"❌ Lỗi SGF: {e}")

        # Xuất TXT (định dạng Lavender)
        txt_fn = f"logs/vncaro_match_{ts}{model_str}{elo_str}.txt"
        try:
            with open(txt_fn, 'w', encoding='utf-8') as f:
                neutral_1d = [r*20+c+1 for r,c in self.neutral_cells]
                moves_str = []
                for i, m in enumerate(self.move_history):
                    p_str = 'X' if m[2] == 1 else 'O'
                    moves_str.append(f"{i+1}.{p_str}:{m[0]*20+m[1]+1}")
                f.write(f"Kết quả: {result}\n")
                f.write(f"Đối thủ ELO: {opp_elo}\n")
                f.write(f"MCTS: {self.simulations} sims, {self.mcts_time}s\n\n")
                f.write(f"Log Game: Trung lập: {neutral_1d} | Nước đi: {' -> '.join(moves_str)}\n\n")
                f.write("Bàn cờ cuối:\n")
                for r in range(19):
                    row = ""
                    for c in range(19):
                        if board[r,c]==1: row+="X "
                        elif board[r,c]==-1: row+="O "
                        else: row+=". "
                    f.write(row+"\n")
            self.log(f"💾 Xuất TXT: {txt_fn}")
        except Exception as e:
            self.log(f"❌ Lỗi TXT: {e}")

        # Reset
        self.pkl_history = []
        self.move_history = []

    def read_board(self, page):
        board_data = page.evaluate('''() => {
            const cells = document.querySelectorAll('.cell');
            if(cells.length !== 361) return null;
            let data = [];
            for(let i=0; i<361; i++) {
                let clone = cells[i].cloneNode(true);
                let stones = clone.querySelectorAll('.dc-stone, .dc-coord');
                stones.forEach(s => s.remove());
                let text = clone.innerText.trim().toUpperCase();
                let bg = window.getComputedStyle(cells[i]).backgroundColor;
                let isN = cells[i].classList.contains('neutral') || cells[i].classList.contains('forb') || 
                          bg === 'rgb(51, 51, 51)' || bg === 'rgb(34, 34, 34)' ||
                          bg === 'rgb(55, 65, 81)' ||
                          bg === '#333' || bg === '#222';
                data.push({text: text, isN: isN});
            }
            return data;
        }''')
        if not board_data: return None, None, 0, 0

        board = np.zeros((19,19), dtype=np.int8)
        neutral = []
        xc, oc = 0, 0
        for i, d in enumerate(board_data):
            r, c = i//19, i%19
            if d['isN']:
                board[r, c] = 2
                neutral.append((r,c))
            elif d['text']=='X': board[r,c]=1; xc+=1
            elif d['text']=='O': board[r,c]=-1; oc+=1
        self.neutral_cells = neutral
        if len(neutral) == 0 and self.engine.rule_type == 3 and (xc + oc) > 0:
            self.log("  ⚠️ KHÔNG TÌM THẤY Ô TRUNG LẬP NÀO!")
        return board, neutral, xc, oc

    # --- Lấy ELO đối thủ ---
    def get_opp_elo(self, page):
        try:
            js = """(() => {
                let px = document.getElementById('px-elo');
                let po = document.getElementById('po-elo');
                return {px: px ? px.innerText : '', po: po ? po.innerText : ''};
            })()"""
            elos = page.evaluate(js)
            # Nếu mình là X thì đối thủ ở po, ngược lại
            raw = elos['po'] if self.play_as_x else elos['px']
            return raw.replace(' ','').replace('ELOAI','elo').replace('ELO','elo') if raw else "unknown"
        except:
            return "unknown"

    # --- MAIN LOOP ---
    def run(self):
        # Redirect print() vào GUI
        gui_stdout = GUIStream(self.log_signal)
        sys.stdout = gui_stdout
        sys.stderr = gui_stdout

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.log("❌ Thiếu Playwright! pip install playwright && playwright install")
            return

        self.log("Khởi tạo Não bộ AI (HybridEngine)...")
        self.engine = DCEngine(rule_type=3, mcts_simulations=self.simulations, custom_exe_path=self.custom_engine_path)

        # Auto-load model mới nhất
        best, bnum = None, -1
        search_dirs = [
            "./models",
            "../models"
        ]
        for mdir in search_dirs:
            if not os.path.exists(mdir): continue
            for f in os.listdir(mdir):
                if f.endswith(".bin.gz"):
                    # Hỗ trợ cả "model_v131.pth" và "caro_ai_v131.pth" / "caro_ai_v131_10x128.pth"
                    import re
                    m = re.search(r'v(\d+)', f)
                    if m:
                        try:
                            n = int(m.group(1))
                            if n > bnum: bnum=n; best=os.path.join(mdir, f)
                        except: pass
        if best:
            success = self.engine.load_model(best)
            if success is False:
                self.log("====================================")
                self.log("[!] BỎ QUA AI: Không tìm thấy thư mục Engine!")
                self.log("[+] Đã tự động kích hoạt chế độ: THUẦN GHI LOG / CHƠI THỦ CÔNG.")
                self.log("====================================")
                self.mode = "manual"
                self.log_signal.emit("CMD_FORCE_MANUAL")
            else:
                self.model_name = os.path.basename(best).replace('.bin.gz','')
                self.log(f"[OK] Não bộ AI: {os.path.basename(best)}")
        else:
            self.log("====================================")
            self.log("[!] BỎ QUA AI: Không tìm thấy file Models!")
            self.log("[+] Đã tự động kích hoạt chế độ: THUẦN GHI LOG / CHƠI THỦ CÔNG.")
            self.log("====================================")
            self.mode = "manual"
            self.log_signal.emit("CMD_FORCE_MANUAL")

        with sync_playwright() as p:
            try:
                self.log("Đang mở Chrome An Toàn (Sandbox)...")
                os.makedirs("chrome_profile", exist_ok=True)
                user_data_dir = os.path.abspath("chrome_profile")
                
                browser_context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=False,
                    no_viewport=True,
                    ignore_default_args=["--enable-automation"],
                    args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
                )
                self.log("[OK] Mở Chrome thành công!")
                
                page = None
                for pg in browser_context.pages:
                    if "vncaro.com" in pg.url: page = pg; break
                if not page:
                    if len(browser_context.pages) > 0:
                        page = browser_context.pages[0]
                    else:
                        page = browser_context.new_page()
                    page.goto("https://vncaro.com/")
                else:
                    self.log("[OK] Đã ghim Tab VnCaro!")
            except Exception as e:
                self.log(f"❌ Lỗi mở Chrome: {e}")
                return
            
            self.page = page  # Lưu reference cho GUI (overlay)

            self.log("\n>>> SẴN SÀNG! VUI LÒNG BẤM [BẮT ĐẦU] Ở BÊN TRÁI <<<\n")

            prev_total_moves = -1  # Theo dõi tổng quân để biết đối thủ đã đi chưa

            while self.is_running:
                time.sleep(0.3)
                if not self.active:
                    self.phan_tich_ngam_thread = None
                    # Vẫn xử lý JS commands khi không active
                    if self.page:
                        check_init = self.page.evaluate("typeof window.drawAllNumbers !== 'undefined'")
                        if not check_init:
                            self.page.evaluate('''
                                window.showCoords = false;
                                window.useGomokuUI = true;
                                window.drawAllNumbers = function() {
                                    var cells = document.querySelectorAll('.cell');
                                    if(cells.length !== 361) return;
                                    for(var i=0; i<361; i++){
                                        var cell = cells[i];
                                        cell.style.position = 'relative';
                                        
                                        var old = cell.querySelectorAll('.dc-stone, .dc-coord');
                                        old.forEach(function(e){ e.remove(); });
                                        
                                        if(window.useGomokuUI) {
                                            cell.style.color = 'transparent';
                                        } else {
                                            cell.style.color = '';
                                        }
                                        
                                        if(window.showCoords) {
                                            var r=Math.floor(i/19), c=i%19;
                                            var cols = 'ABCDEFGHJKLMNOPQRST';
                                            var id = cols[c] + (19 - r);
                                            var lbl = document.createElement('div');
                                            lbl.className = 'dc-coord';
                                            lbl.textContent = id;
                                            lbl.style.cssText = 'position:absolute; top:2px; left:2px; font-size:9px; font-weight:bold; color:#ff0000; z-index:10; pointer-events:none; opacity:0.8;';
                                            cell.appendChild(lbl);
                                        }
                                    }
                                    if(window.botMoveHistory && window.useGomokuUI) {
                                        for(var m=0; m<window.botMoveHistory.length; m++) {
                                            var move = window.botMoveHistory[m];
                                            var idx = move[0]*19 + move[1];
                                            var who = move[2];
                                            var cell = cells[idx];
                                            if(cell) {
                                                var stone = document.createElement('div');
                                                stone.className = 'dc-stone';
                                                var isBlack = (who === 1);
                                                var bg = isBlack ? 'radial-gradient(circle at 30% 30%, #555, #000)' : 'radial-gradient(circle at 30% 30%, #fff, #ccc)';
                                                var fg = isBlack ? '#fff' : '#000';
                                                var border = (m === window.botMoveHistory.length - 1) ? '2px solid red' : (isBlack ? '1px solid #000' : '1px solid #999');
                                                stone.style.cssText = 'position:absolute; width:80%; height:80%; top:10%; left:10%; border-radius:50%; background:' + bg + '; border:' + border + '; display:flex; align-items:center; justify-content:center; color:' + fg + '; font-size:12px; font-weight:bold; font-family:Arial; z-index:5; pointer-events:none; box-shadow: 2px 2px 4px rgba(0,0,0,0.4);';
                                                stone.textContent = (m + 1).toString();
                                                cell.appendChild(stone);
                                            }
                                        }
                                    }
                                };
                            ''')
                    if self.page and self.pending_js:
                        for js in self.pending_js:
                            try: self.page.evaluate(js)
                            except: pass
                        self.pending_js.clear()
                    continue

                try:
                    # Xử lý JS commands từ GUI (overlay, etc)
                    if self.page and self.pending_js:
                        for js in self.pending_js:
                            try: self.page.evaluate(js)
                            except: pass
                    self.engine.mcts_simulations = self.simulations
                    
                    # Tự động dò tìm Tab vncaro và frame có chứa bàn cờ
                    target_frame = None
                    cell_count = 0
                    found_page = None
                    
                    try:
                        for pg in browser_context.pages:
                            if "vncaro.com" in pg.url:
                                for frame in pg.frames:
                                    try:
                                        cnt = frame.evaluate("document.querySelectorAll('.cell').length")
                                        if cnt > 0:
                                            cell_count = cnt
                                            target_frame = frame
                                            found_page = pg
                                            break
                                    except: pass
                                if target_frame: break
                    except: pass
                    
                    # Cập nhật lại page nếu có thay đổi tab
                    if found_page and self.page != found_page:
                        self.page = found_page
                        
                    page = self.page

                    if target_frame is None:
                        # Nếu không có frame nào chứa `.cell`, có thể sếp chưa vào phòng game
                        if not hasattr(self, 'last_cell_warn') or self.last_cell_warn != 0:
                            self.log(f"⚠️ Đang dò tìm bàn cờ... (Đếm được 0 ô). Hãy vào phòng game!")
                            self.last_cell_warn = 0
                        continue
                        
                    if cell_count != 361:
                        if not hasattr(self, 'last_cell_warn') or self.last_cell_warn != cell_count:
                            self.log(f"⚠️ Cảnh báo: Đếm được {cell_count} ô (cần 361 ô). Đang ở tab: {page.url[:50]}")
                            self.last_cell_warn = cell_count
                        continue
                        
                    cells = target_frame.locator(".cell").all()

                    board, neutral, xc, oc = self.read_board(target_frame)
                    if board is None:
                        if not hasattr(self, 'last_board_warn'):
                            self.log("⚠️ Bàn cờ đọc ra bị NULL!")
                            self.last_board_warn = True
                        continue

                    # Auto nhận diện phe (Cải tiến)
                    my_p = target_frame.evaluate('''(() => {
                        if (typeof myP !== "undefined") return myP;
                        if (typeof mySide !== "undefined") return mySide;
                        if (typeof isX !== "undefined") return isX ? "X" : "O";
                        // Dò class trên board
                        if (document.body.classList.contains("playing-x")) return "X";
                        if (document.body.classList.contains("playing-o")) return "O";
                        // Dò class trên container
                        let b = document.querySelector(".board");
                        if (b) {
                            if (b.classList.contains("x-turn") || b.className.includes("player-x")) return "X";
                            if (b.classList.contains("o-turn") || b.className.includes("player-o")) return "O";
                        }
                        return null;
                    })()''')
                    if my_p == 'X':
                        if not self.play_as_x:
                            # Lưu ván cũ trước khi xóa
                            if len(self.move_history) > 0:
                                self.save_match_log(board, "RESET / VÁN MỚI")
                                
                            self.move_history.clear()
                            self.history_signal.emit(self.move_history, self.engine.board_size if self.engine else 20)
                            self.pkl_history.clear()
                            self.play_as_x = True
                            self.side_detected.emit(True)
                    elif my_p == 'O':
                        if self.play_as_x:
                            # Lưu ván cũ trước khi xóa
                            if len(self.move_history) > 0:
                                self.save_match_log(board, "RESET / VÁN MỚI")
                                
                            self.move_history.clear()
                            self.history_signal.emit(self.move_history, self.engine.board_size if self.engine else 20)
                            self.pkl_history.clear()
                            self.play_as_x = False
                            self.side_detected.emit(False)

                    # Check game over
                    is_over = target_frame.evaluate('typeof over !== "undefined" ? over : false')
                    if not is_over:
                        self.match_saved = False
                        
                    if is_over:
                        self.phan_tich_ngam_thread = None
                        
                        if getattr(self, 'match_saved', False):
                            # Đã lưu log cho ván này rồi, chỉ chờ tìm trận mới
                            if self.auto_farm:
                                page.evaluate('let closeBtn = document.querySelector(".result-close-btn") || document.querySelector(".ant-modal-close"); if(closeBtn) closeBtn.click();')
                                page.evaluate('let btns=Array.from(document.querySelectorAll("button")); let playAgain=btns.find(b=>b.textContent&&b.textContent.includes("Chơi tiếp")); if(playAgain){playAgain.click();}else{let actionBtn=document.querySelector("#result-action-btn"); if(actionBtn){actionBtn.click();}else{let b=btns.find(b=>b.textContent&&(b.textContent.includes("Tìm trận")||b.textContent.includes("Tìm đối thủ")||b.textContent.includes("Chơi với máy")||b.textContent.includes("Đánh với máy"))); if(b)b.click();}}')
                            continue
                            
                        self.match_saved = True
                        
                        # === ĐỌC BOARD LẦN CUỐI để bắt nước đi còn thiếu ===
                        try:
                            final_board, final_neutral, _, _ = self.read_board(target_frame)
                            if final_board is not None and self.last_board is not None:
                                diff = final_board - self.last_board
                                new_moves_raw = np.argwhere((diff != 0) & (final_board != 0) & (final_board != 2))
                                if len(new_moves_raw) > 0:
                                    last_xc = np.sum(self.last_board == 1)
                                    last_oc = np.sum(self.last_board == -1)
                                    next_turn = 1 if last_xc == last_oc else -1
                                    moves_x = [(r, c, 1) for r, c in new_moves_raw if final_board[r, c] == 1]
                                    moves_o = [(r, c, -1) for r, c in new_moves_raw if final_board[r, c] == -1]
                                    sorted_final = []
                                    while moves_x or moves_o:
                                        if next_turn == 1 and moves_x:
                                            sorted_final.append(moves_x.pop(0)); next_turn = -1
                                        elif next_turn == -1 and moves_o:
                                            sorted_final.append(moves_o.pop(0)); next_turn = 1
                                        else:
                                            if moves_x: sorted_final.append(moves_x.pop(0))
                                            if moves_o: sorted_final.append(moves_o.pop(0))
                                    
                                    current_sim_board = self.last_board.copy()
                                    neutral = final_neutral or self.neutral_cells
                                    for rm, cm, pv in sorted_final:
                                        self.move_history.append((rm, cm, pv))
                                        tg = CaroGame(rule_type=self.engine.rule_type)
                                        tg.board = current_sim_board.copy()
                                        tg.neutral_cells = neutral
                                        state = tg.get_state_tensor(pv)
                                        pi = np.zeros(361, dtype=np.float32)
                                        pi[rm*19+cm] = 1.0
                                        self.pkl_history.append((state, pi, pv))
                                        current_sim_board[rm, cm] = pv
                                    self.last_board = final_board.copy()
                                    board = final_board
                                    self.log(f"  📝 Bắt thêm {len(sorted_final)} nước cuối")
                        except Exception as e:
                            self.log(f"  ⚠️ Lỗi đọc board cuối: {e}")
                        self.log("  📝 Ghi nhận nốt nước chốt hạ.")
                        win_text = target_frame.evaluate('''(() => {
                                    // 1. Thử các class phổ biến của Bootstrap / SweetAlert
                                    let selectors = [
                                        ".modal.show .modal-title",
                                        "#result-modal .modal-title",
                                        ".modal.show .modal-body",
                                        ".modal.show h4",
                                        ".modal.show h5",
                                        ".swal2-title",
                                        ".swal2-html-container"
                                    ];
                                    for (let sel of selectors) {
                                        let el = document.querySelector(sel);
                                        if (el && el.innerText && el.innerText.trim().length > 0) {
                                            return el.innerText.trim();
                                        }
                                    }
                                    // 2. Thử lấy từ bất kỳ element nào chứa "thắng" hoặc "thua"
                                    let allModals = document.querySelectorAll(".modal.show *");
                                    for (let el of allModals) {
                                        let t = el.innerText || "";
                                        if (t.includes("thắng") || t.includes("thua") || t.includes("Thắng") || t.includes("Thua") || t.includes("hòa") || t.includes("Hòa")) {
                                            return t.split("\\n")[0];
                                        }
                                    }
                                    return "";
                                })()
                            ''')
                        # Xác định người thắng (vncaro.com: "Chiến thắng" / "Thất bại" / "Hòa")
                        winner_char = "Không rõ"
                        if win_text:
                            wt = win_text.lower()
                            if "chiến thắng" in wt or "thắng" in wt:
                                winner_char = my_p
                            elif "thất bại" in wt or "thua" in wt or "hết giờ" in wt:
                                winner_char = 'O' if my_p == 'X' else 'X'
                            elif "hòa" in wt or "draw" in wt:
                                winner_char = 'Hòa'
                        
                        # Fallback: nếu không đọc được text, tự kiểm tra bàn cờ
                        if winner_char == "Không rõ" and board is not None:
                            try:
                                def check_win(b, p):
                                    for r in range(19):
                                        for c in range(19):
                                            if b[r,c] == p:
                                                if c<=14 and all(b[r,c+i]==p for i in range(5)): return True
                                                if r<=14 and all(b[r+i,c]==p for i in range(5)): return True
                                                if r<=14 and c<=14 and all(b[r+i,c+i]==p for i in range(5)): return True
                                                if r>=4 and c<=14 and all(b[r-i,c+i]==p for i in range(5)): return True
                                    return False
                                if check_win(board, 1): winner_char = "X"
                                elif check_win(board, -1): winner_char = "O"
                            except: pass
                        if winner_char in self.stats:
                            self.stats[winner_char] += 1
                            
                        self.log(f"\n🎉 WEB BÁO KẾT THÚC! ({win_text}) -> Kết thúc trận, {winner_char} THẮNG!")
                        self.log(f"📊 THỐNG KÊ LỊCH SỬ: 🔴 X thắng {self.stats['X']} trận | 🔵 O thắng {self.stats['O']} trận | ⚪ Hòa {self.stats['Hòa']} trận")
                        
                        opp_elo = self.get_opp_elo(target_frame)
                        self.save_match_log(board, win_text or "Kết thúc", opp_elo)

                        if self.auto_farm:
                            self.log("⏳ Nghỉ 4s rồi tìm trận mới...")
                            time.sleep(4)
                            if not self.active: continue
                            self.log("🚀 Tìm trận mới!")
                            page.evaluate('let closeBtn = document.querySelector(".result-close-btn") || document.querySelector(".ant-modal-close"); if(closeBtn) closeBtn.click();')
                            time.sleep(1)
                            page.evaluate('let btns=Array.from(document.querySelectorAll("button")); let playAgain=btns.find(b=>b.textContent&&b.textContent.includes("Chơi tiếp")); if(playAgain){playAgain.click();}else{let actionBtn=document.querySelector("#result-action-btn"); if(actionBtn){actionBtn.click();}else{let b=btns.find(b=>b.textContent&&(b.textContent.includes("Tìm trận")||b.textContent.includes("Tìm đối thủ")||b.textContent.includes("Chơi với máy")||b.textContent.includes("Đánh với máy"))); if(b)b.click();}}')
                            self.last_board = None
                            prev_total_moves = -1
                            time.sleep(3)
                        else:
                            self.log("[⏸️] Auto-Farm TẮT -> Dừng.")
                            self.active = False
                            self.stopped_signal.emit()
                        continue

                    # Ghi nhận nước đi mới
                    if self.last_board is None:
                        self.last_board = board.copy()
                        self.move_history = []
                        self.pkl_history = []
                        try:
                            page.evaluate("window.botMoveHistory = []; if(window.drawAllNumbers) window.drawAllNumbers();")
                        except: pass

                    diff = board - self.last_board
                    new_moves_raw = np.argwhere((diff != 0) & (board != 0))
                    
                    if len(new_moves_raw) > 0:
                        # 1. Sắp xếp nước đi đúng thứ tự thời gian (X, O luân phiên)
                        last_xc = np.sum(self.last_board == 1)
                        last_oc = np.sum(self.last_board == -1)
                        next_turn = 1 if last_xc == last_oc else -1
                        
                        moves_x = [(r, c, 1) for r, c in new_moves_raw if board[r, c] == 1]
                        moves_o = [(r, c, -1) for r, c in new_moves_raw if board[r, c] == -1]
                        
                        sorted_new_moves = []
                        while moves_x or moves_o:
                            if next_turn == 1 and moves_x:
                                sorted_new_moves.append(moves_x.pop(0))
                                next_turn = -1
                            elif next_turn == -1 and moves_o:
                                sorted_new_moves.append(moves_o.pop(0))
                                next_turn = 1
                            else:
                                if moves_x: sorted_new_moves.append(moves_x.pop(0))
                                if moves_o: sorted_new_moves.append(moves_o.pop(0))
                                
                        # 2. Ghi nhận tuần tự và cập nhật bàn cờ trung gian
                        current_sim_board = self.last_board.copy()
                        for rm, cm, pv in sorted_new_moves:
                            self.move_history.append((rm, cm, pv))
                            
                            tg = CaroGame(rule_type=self.engine.rule_type)
                            tg.board = current_sim_board.copy()
                            tg.neutral_cells = neutral
                            
                            state = tg.get_state_tensor(pv)
                            
                            # Nước Bot: dùng MCTS policy distribution (chất lượng cao hơn)
                            # Nước Đối thủ: dùng one-hot
                            my_player = 1 if self.play_as_x else -1
                            if pv == my_player and self.last_mcts_policy is not None:
                                pi = self.last_mcts_policy.copy()
                                self.last_mcts_policy = None  # Reset sau khi dùng
                            else:
                                pi = np.zeros(361, dtype=np.float32)
                                pi[rm*19+cm] = 1.0
                            self.pkl_history.append((state, pi, pv))
                            
                            # Cập nhật board tạm cho nước tiếp theo
                            current_sim_board[rm, cm] = pv
                            
                        self.last_board = board.copy()
                    
                    if len(new_moves_raw) > 0:
                        self.history_signal.emit(self.move_history, self.engine.board_size if self.engine else 20)
                        try:
                            import json
                            hist_json = json.dumps([(int(m[0]), int(m[1]), int(m[2])) for m in self.move_history])
                            page.evaluate(f"window.botMoveHistory = {hist_json}; if(window.drawAllNumbers) window.drawAllNumbers();")
                        except Exception as e:
                            print("JS err:", e)

                    total_moves = xc + oc
                    
                    # Xác định ai đi trước dựa vào nước đi đầu tiên
                    x_went_first = True
                    if total_moves > 0 and len(self.move_history) > 0:
                        first_move_player = self.move_history[0][2]
                        if first_move_player == -1: # O đi trước
                            x_went_first = False
                            
                    if x_went_first:
                        is_x_turn = (xc == oc)
                    else:
                        is_x_turn = (xc < oc)

                    is_my_turn = (self.play_as_x and is_x_turn) or (not self.play_as_x and not is_x_turn)

                    if not is_my_turn:
                        # === PONDERING: Nghĩ trước trong lúc chờ đối thủ ===
                        if self.phan_tich_ngam_thread is None and self.engine.model_loaded:
                            if total_moves != prev_total_moves:
                                prev_total_moves = total_moves
                                self.log(f"  💭 [Phân tích ngầm] Chờ đối thủ...")
                        continue

                    # === LƯỢT BOT ===
                    if self.mode == "manual":
                        # Thủ công thì không tự đánh
                        time.sleep(1)
                        continue
                        
                    my_char = 'X' if self.play_as_x else 'O'
                    player_to_move = 1 if is_x_turn else -1

                    self.log(f"\n[▶] LƯỢT BOT ({my_char}). Đang suy nghĩ tối đa {int(self.mcts_time)}s...")
                    game = CaroGame(rule_type=self.engine.rule_type)
                    game.board = board.copy()
                    game.neutral_cells = neutral
                    game.move_history = [(m[0],m[1]) for m in self.move_history]

                    # Chạy get_move trong thread riêng để GUI không đơ
                    think_thread = PonderThread(self.engine, game, player_to_move, self.mcts_time, self.simulations)
                    think_thread.start()
                    
                    start_t = time.time()
                    last_report = 0
                    while think_thread.is_alive():
                        time.sleep(0.1)
                        elapsed = time.time() - start_t
                        if int(elapsed) > last_report:
                            last_report = int(elapsed)
                            if last_report == 1:
                                self.log(f"  ⏱️ Đang nghĩ... {last_report}s")
                            else:
                                self.log(f"\r  ⏱️ Đang nghĩ... {last_report}s")
                        if not self.active: break
                    
                    think_thread.join(timeout=1)
                    think_time = time.time() - start_t
                    action = think_thread.result_action
                    info = think_thread.result_info or {}

                    self.phan_tich_ngam_thread = None

                    if action is None:
                        err_detail = info.get('detail', '')
                        self.log(f"  ⚠️ Chờ ván cờ sẵn sàng... ({err_detail})")
                        time.sleep(1)
                        continue

                    # Kiểm tra xem Sếp có đánh thay trong lúc AI nghĩ không
                    board_after, _, xc_after, oc_after = self.read_board(page)
                    if board_after is not None:
                        if (self.play_as_x and xc_after > xc) or (not self.play_as_x and oc_after > oc):
                            self.log("  🛑 Sếp đã đánh thay trong lúc AI nghĩ!\n")
                            continue

                    r, c = action//19, action%19
                    method = info.get('method','')
                    detail = info.get('detail','')
                    
                    # === KIỂM TRA LUẬT MỞ MÀN (Nước 1 của X và Nước 2 của X) ===
                    if total_moves == 0 or (total_moves == 2 and self.play_as_x):
                        valid_mask = game.get_valid_moves(True)
                        if valid_mask[action] == 0:
                            self.log(f"  ⚠️ DC_bot chọn ô ({r},{c}) nhưng BỊ CẤM bởi luật mở màn VnCaro3o!")
                            valid_indices = np.where(valid_mask > 0)[0]
                            if len(valid_indices) > 0:
                                action = np.random.choice(valid_indices)
                                r, c = action//19, action%19
                                self.log(f"  👉 Tự động ép đổi sang nước hợp lệ: ({r},{c})")
                                method = "Luật Ép Buộc (Mở màn)"
                                
                    # === KIỂM TRA LAO ĐẦU VÀO TƯỜNG (Ô TRUNG LẬP) ===
                    if (r, c) in game.neutral_cells:
                        self.log(f"  ⚠️ DC_bot mù mắt lao vào ô trung lập ({r},{c})! Ép lách tường.")
                        policy = game.get_heuristic_policy(self.play_as_x)
                        if policy is not None:
                            action = np.argmax(policy)
                            r, c = action//19, action%19
                            method = "Luật Ép Buộc (Tránh Tường)"
                            self.log(f"  👉 Tự động bẻ lái sang: ({r},{c})")

                    self.log(f"  └─> Ô ({r},{c}) | {method} | {think_time:.1f}s")
                    if detail: self.log(f"      {detail}")

                    # Click nháp (chọn ô)
                    cells[action].evaluate("node => node.click()")

                    if self.delay_sec > 0:
                        self.log(f"  ⏳ Đợi {self.delay_sec}s...")
                        for _ in range(int(self.delay_sec * 10)):
                            time.sleep(0.1)
                            if not self.active: break
                            
                        if not self.active:
                            continue

                    # Lưu MCTS policy cho PKL
                    self.last_mcts_policy = info.get('mcts_policy', None)
                    
                    # Chốt nước thật
                    self.log("  ✅ CHỐT!\n")
                    cells[action].evaluate("node => node.click()")
                    time.sleep(0.8)
                    prev_total_moves = total_moves + 1

                except Exception as e:
                    import traceback
                    self.log(f"  ⚠️ Lỗi: {str(e)[:80]}")
                    print(traceback.format_exc())
                    time.sleep(1)
            
            # Đảm bảo đóng trình duyệt an toàn khi kết thúc Thread
            try:
                if 'browser_context' in locals() and browser_context:
                    browser_context.close()
            except: pass

# =============================================
# GUI WINDOW
# =============================================
class BotWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VnCaro DCbot V3.0")
        self.resize(550, 950)
        self.setMinimumWidth(480)
        self.setStyleSheet("font-family: Arial; font-size: 14px;")

        main = QWidget()
        self.setCentralWidget(main)
        lay = QVBoxLayout(main)

        # --- Cày Rank ---
        g1 = QGroupBox("Cày Rank & Phe")
        l1 = QVBoxLayout()
        self.chk_autofarm = QCheckBox("Kích hoạt Auto-Farm (Đánh liên tục)")
        self.chk_autofarm.setStyleSheet("color: #ff5500; font-weight: bold;")
        hp = QHBoxLayout()
        hp.addWidget(QLabel("Phe dự phòng:"))
        self.rb_x = QRadioButton("X"); self.rb_x.setChecked(True)
        self.rb_o = QRadioButton("O")
        hp.addWidget(self.rb_x); hp.addWidget(self.rb_o)
        
        h_mode = QHBoxLayout()
        h_mode.addWidget(QLabel("Chế độ chơi:"))
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["Chơi thủ công (Ghi Log)", "Chơi bằng Model AI"])
        self.cb_mode.setStyleSheet("font-weight: bold; padding: 5px;")
        h_mode.addWidget(self.cb_mode)

        self.btn_help = QPushButton('ℹ️ Bảo mật')
        self.btn_help.setStyleSheet('color: #17a2b8; font-weight: bold; padding: 5px;')
        self.btn_help.setFixedWidth(100)
        self.btn_help.clicked.connect(self.show_security_info)
        h_mode.addWidget(self.btn_help)
        
        l1.addWidget(self.chk_autofarm); l1.addLayout(h_mode); l1.addLayout(hp)
        g1.setLayout(l1); lay.addWidget(g1)

        # --- Não Bộ ---
        self.g2 = QGroupBox("Cấu Hình Não Bộ")
        l2 = QVBoxLayout()

        hm = QHBoxLayout()
        self.btn_model = QPushButton("Chọn File Não")
        self.btn_model.clicked.connect(self.choose_model)
        self.lbl_model = QLabel("Auto (Mới nhất)")
        self.lbl_model.setStyleSheet("color: #007bff; font-weight: bold;")
        hm.addWidget(self.btn_model); hm.addWidget(self.lbl_model)
        l2.addLayout(hm)
        
        he = QHBoxLayout()
        self.btn_engine = QPushButton("Chọn File GPU")
        self.btn_engine.clicked.connect(self.choose_engine)
        self.lbl_engine = QLabel("Auto (Mặc định)")
        self.lbl_engine.setStyleSheet("color: #28a745; font-weight: bold;")
        he.addWidget(self.btn_engine); he.addWidget(self.lbl_engine)
        l2.addLayout(he)

        # Cấu hình maxVisits thủ công
        h_visits = QHBoxLayout()
        self.lbl_max_visits = QLabel("Số vòng nghĩ tối đa:")
        self.spin_max_visits = NoScrollSpinBox()
        self.spin_max_visits.setRange(10, 50000)
        self.spin_max_visits.setValue(500)
        self.spin_max_visits.setSingleStep(50)
        self.spin_max_visits.setFixedWidth(80)
        self.spin_max_visits.setFocusPolicy(Qt.StrongFocus)
        self.spin_max_visits.setStyleSheet("font-size:16px; font-weight:bold;")
        self.btn_apply_visits = QPushButton("Áp dụng")
        self.btn_apply_visits.setStyleSheet("color: #ff5500; font-weight: bold;")
        self.btn_apply_visits.clicked.connect(self.apply_max_visits)
        
        h_visits.addWidget(self.lbl_max_visits)
        h_visits.addWidget(self.spin_max_visits)
        h_visits.addWidget(self.btn_apply_visits)
        h_visits.addStretch()
        l2.addLayout(h_visits)

        # Cấp độ AI (1-10)
        h_lv = QHBoxLayout()
        h_lv.addWidget(QLabel("Cấp độ AI:"))
        self.spin_level = NoScrollSpinBox()
        self.spin_level.setRange(1, 10)
        self.spin_level.setValue(5)
        self.spin_level.setFixedWidth(80)
        self.spin_level.setFocusPolicy(Qt.StrongFocus)
        self.spin_level.setStyleSheet("font-size:16px; font-weight:bold;")
        self.lbl_level_desc = QLabel("Trung bình (10s, 400 sims)")
        self.lbl_level_desc.setStyleSheet("color:#888;")
        h_lv.addWidget(self.spin_level)
        h_lv.addWidget(self.lbl_level_desc)
        h_lv.addStretch()
        l2.addLayout(h_lv)
        self.spin_level.valueChanged.connect(self.on_level_changed)

        # Đợi chốt nước
        h_delay = QHBoxLayout()
        h_delay.addWidget(QLabel("Đợi chốt nước (giây):"))
        self.spin_delay = NoScrollDoubleSpinBox()
        self.spin_delay.setRange(0, 10); self.spin_delay.setValue(3); self.spin_delay.setSingleStep(0.5)
        self.spin_delay.setFixedWidth(80)
        self.spin_delay.setFocusPolicy(Qt.StrongFocus)
        h_delay.addWidget(self.spin_delay)
        h_delay.addStretch()
        l2.addLayout(h_delay)

        self.chk_ponder = QCheckBox("Bật Phân tích ngầm (Nghĩ cả trong giờ đối thủ)")
        self.chk_ponder.setStyleSheet("font-weight: bold; color: #17a2b8;")
        # Read current state
        try:
            with open("gtp.cfg", 'r', encoding='utf-8') as f:
                txt = f.read()
                if "ponderingEnabled = true" in txt or "ponderingEnabled=true" in txt:
                    self.chk_ponder.setChecked(True)
        except: pass
        self.chk_ponder.toggled.connect(self.update_ponder_cfg)
        l2.addWidget(self.chk_ponder)

        self.g2.setLayout(l2); lay.addWidget(self.g2)

        # --- Nút ---
        h_btns = QHBoxLayout()
        self.btn_go = QPushButton("BẮT ĐẦU BOT")
        self.btn_go.setStyleSheet("background:#28a745;color:white;font-weight:bold;font-size:18px;padding:15px;")
        self.btn_go.clicked.connect(self.toggle_bot)
        
        self.btn_review = QPushButton("Xem lại ván đấu")
        self.btn_review.setStyleSheet("background:#17a2b8;color:white;font-weight:bold;font-size:18px;padding:15px;")
        self.btn_review.clicked.connect(self.open_review)
        
        h_btns.addWidget(self.btn_go)
        h_btns.addWidget(self.btn_review)
        lay.addLayout(h_btns)

        # --- Nút tọa độ + Opacity ---
        h_ov = QHBoxLayout()
        self.btn_overlay = QPushButton("👁️ Hiện tọa độ")
        self.btn_overlay.setStyleSheet("background:#6c757d;color:white;font-weight:bold;padding:8px;")
        self.btn_overlay.setCheckable(True)
        self.btn_overlay.clicked.connect(self.toggle_overlay)
        h_ov.addWidget(self.btn_overlay)
        
        self.chk_gomoku_ui = QCheckBox("Giao diện Gomoku 3D")
        self.chk_gomoku_ui.setChecked(True)
        self.chk_gomoku_ui.setStyleSheet("font-weight: bold; color: #007bff;")
        self.chk_gomoku_ui.stateChanged.connect(self.toggle_gomoku_ui)
        h_ov.addWidget(self.chk_gomoku_ui)
        
        h_ov.addWidget(QLabel("🫧 Mờ:"))
        self.slider_opa = QSlider(Qt.Horizontal)
        self.slider_opa.setRange(10, 100)
        self.slider_opa.setValue(60)
        self.slider_opa.valueChanged.connect(self.change_overlay_opacity)
        self.lbl_opa = QLabel("60%")
        h_ov.addWidget(self.slider_opa)
        h_ov.addWidget(self.lbl_opa)
        lay.addLayout(h_ov)

        # --- Phân chia Khu vực Log và Lịch sử Nước Đi ---
        from PyQt5.QtWidgets import QSplitter
        
        # Log Panel
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.txt_log.setStyleSheet("background:#1e1e1e;color:#00ff00;font-family:Consolas;font-size:12px;")
        self.txt_log.setMinimumHeight(400)
        
        # History Panel
        self.txt_history = QTextEdit()
        self.txt_history.setReadOnly(True)
        self.txt_history.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.txt_history.setStyleSheet("background:#1e1e1e;color:#ffaa00;font-family:Consolas;font-size:12px;font-weight:bold;")
        self.txt_history.setText("LỊCH SỬ NƯỚC ĐI\n" + "-"*30)
        self.txt_history.setMinimumHeight(400)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.txt_log)
        splitter.addWidget(self.txt_history)
        splitter.setSizes([600, 300])  # Tỷ lệ 2/3 và 1/3
        lay.addWidget(splitter)

        # Live update signals
        for w in [self.chk_autofarm, self.rb_x, self.rb_o]:
            w.toggled.connect(self.update_params) if hasattr(w,'toggled') else w.stateChanged.connect(self.update_params)
        self.spin_delay.valueChanged.connect(self.update_params)

        # Thread
        self.bot = BotThread()
        self.bot.log_signal.connect(self.append_log)
        self.bot.history_signal.connect(self.update_history_ui)
        self.bot.side_detected.connect(self.update_side_ui)
        self.bot.stopped_signal.connect(self.bot_stopped)
        
        # Initialize UI state based on mode
        self.cb_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.on_mode_changed(self.cb_mode.currentIndex())
        
        self.bot.start()

    def show_security_info(self):
        msg = QMessageBox(self)
        msg.setWindowTitle('Thông tin Bảo mật')
        msg.setText(
            '<b>Cửa sổ Chrome trắng tinh là một vùng an toàn (Sandbox).</b><br><br>'
            'Nó <b>không hề đụng chạm, quét, hay đọc</b> bất kỳ lịch sử duyệt web, cookie, '
            'hay tài khoản ngân hàng nào đang lưu trong trình duyệt chính của bạn.<br><br>'
            'Ngược lại, nếu kết nối tool vào trình duyệt chính đang mở sẵn, '
            'rủi ro bị lộ lọt toàn bộ mật khẩu cá nhân sẽ rất cao nếu xảy ra lỗi bảo mật.<br><br>'
            'Với cửa sổ trắng độc lập này, bạn <b>chỉ cần đăng nhập VnCaro 1 lần duy nhất</b>, '
            'các lần sau mở tool lên nó sẽ tự nhớ phiên đăng nhập (thông qua thư mục <i>chrome_profile</i>).'
        )
        msg.exec_()

    def update_side_ui(self, is_x):
        self.rb_x.blockSignals(True)
        self.rb_o.blockSignals(True)
        self.rb_x.setChecked(is_x)
        self.rb_o.setChecked(not is_x)
        self.rb_x.blockSignals(False)
        self.rb_o.blockSignals(False)
        phe_str = "X (Đi trước, theo luật mở màn)" if is_x else "O (Đi sau, không bị cấm)"
        self.append_log(f"\n[🤖] TỰ ĐỘNG NHẬN DIỆN: Bot đang cầm phe {phe_str}")

    def update_history_ui(self, move_history, board_size):
        lines = [f"{'STT':<4}| {'SỐ':<8}| {'CHỮ'}", "-"*25]
        letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
        for i, m in enumerate(move_history):
            # Cấu trúc m có thể là (r, c) hoặc (r, c, p)
            if len(m) == 3:
                r, c, p = m
            else:
                r, c = m[:2]
                # Nội suy p nếu chỉ có r,c (Nước lẻ là X, chẵn là O)
                p = 1 if i % 2 == 0 else -1
                
            p_str = "X" if p == 1 else "O"
            idx = r * board_size + c
            
            # Format chữ (vd: D5)
            col_letter = letters[c] if c < len(letters) else "?"
            row_num = board_size - r
            gtp_move = f"{col_letter}{row_num}"
            
            lines.append(f"{i+1:<4}| {p_str}:{idx:<5}| {p_str}:{gtp_move}")
            
        self.txt_history.setText("\n".join(lines))
        # Cuộn xuống dòng cuối cùng
        scrollbar = self.txt_history.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_ponder_cfg(self):
        val = self.chk_ponder.isChecked()
        cfg_path = "gtp.cfg"
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                import re
                content = re.sub(r"^[#\s]*ponderingEnabled\s*=\s*(true|false).*$", f"ponderingEnabled = {'true' if val else 'false'}", content, flags=re.MULTILINE)
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.append_log(f"\n[⚙️] Đã {'BẬT' if val else 'TẮT'} chế độ Phân tích ngầm (Sẽ có tác dụng từ ván sau hoặc khi Chọn lại Model).")
            except Exception as e:
                self.append_log(f"[!] Lỗi khi đổi gtp.cfg: {e}")

    def open_review(self):
        import webbrowser, os, sys
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.abspath(".")
        path = os.path.join(base_path, 'index.html')
        if os.path.exists(path):
            webbrowser.open('file://' + path)
        else:
            QMessageBox.warning(self, "Lỗi", "Không tìm thấy file index.html")

    def choose_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file Engine .exe", "", "Executable Files (*.exe);;All Files (*)")
        if path:
            self.bot.custom_engine_path = path
            self.lbl_engine.setText(os.path.basename(path))
            self.append_log(f"\n[OK] Đã chọn Engine: {os.path.basename(path)}")
            if self.bot.engine:
                self.append_log("[!] Lưu ý: Bạn cần khởi động lại quá trình 'BẮT ĐẦU BOT' để áp dụng Engine mới!")

    def choose_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn File Não", "", "DC_bot Model (*.bin.gz);;All Files (*.*)")
        if path:
            if not path.endswith('.bin.gz'):
                QMessageBox.warning(self, "Lỗi", "File không tương thích, hãy chọn lại file phù hợp.")
                return
            if self.bot.engine:
                name = os.path.basename(path)
                
                self.append_log(f"\n[!] Đang nạp {name}... (Quá trình này mất 1-3 phút. NẾU BỊ TREO/NOT RESPONDING SẾP CỨ ĐỂ YÊN NHÉ, NÓ ĐANG NẠP VÀO CARD ĐỒ HỌA!)")
                QApplication.processEvents()  # Ép màn hình hiển thị dòng log trên ngay lập tức trước khi bị freeze
                
                self.bot.model_path = path
                success = self.bot.engine.load_model(path, max_visits=self.spin_max_visits.value())
                
                if success:
                    self.bot.model_name = name.replace('model_','').replace('.bin.gz','')
                    self.lbl_model.setText(name)
                    self.append_log(f"[OK] Đã nạp xong Não: {name}")
                else:
                    self.append_log(f"[LỖI] KHÔNG THỂ nạp Não. Đảm bảo thư mục 'engine' chứa caro20x_opencl.exe nằm CÙNG CHỖ với file Bot này!")
                    QMessageBox.warning(self, "Lỗi Nạp Não", "Nạp thất bại! Thiếu file engine C++ hoặc model bị lỗi.\nSếp hãy đảm bảo đã copy thư mục 'engine' để nằm chung với file Bot .exe nhé.")

    def apply_max_visits(self):
        if self.bot.engine and hasattr(self.bot, 'model_path') and self.bot.model_path:
            self.append_log(f"\n[!] Đang áp dụng Sức mạnh mới (maxVisits = {self.spin_max_visits.value()})...")
            QApplication.processEvents()
            success = self.bot.engine.load_model(self.bot.model_path, max_visits=self.spin_max_visits.value())
            if success:
                self.append_log("[OK] Đã áp dụng Sức mạnh thành công!")
        else:
            self.append_log("\n[LỖI] Bạn chưa nạp File Não nên không thể áp dụng Sức mạnh!")

    def toggle_overlay(self, checked):
        if not self.bot.page:
            self.append_log("[!] Chưa kết nối Chrome!")
            self.btn_overlay.setChecked(False)
            return
        if checked:
            self.btn_overlay.setStyleSheet("background:#17a2b8;color:white;font-weight:bold;padding:8px;")
            self.btn_overlay.setText("👀 Ẩn tọa độ")
            js = (
                "window.showCoords = true;"
                "if(window.drawAllNumbers) window.drawAllNumbers();"
            )
            self.bot.pending_js.append(js)
            self.append_log("[OK] Đã hiện tọa độ (A1-T19) trên bàn cờ!")
        else:
            self.btn_overlay.setStyleSheet("background:#6c757d;color:white;font-weight:bold;padding:8px;")
            self.btn_overlay.setText("👁️ Hiện tọa độ")
            js = (
                "window.showCoords = false;"
                "if(window.drawAllNumbers) window.drawAllNumbers();"
            )
            self.bot.pending_js.append(js)
            self.append_log("[OK] Đã ẩn tọa độ.")

    def toggle_gomoku_ui(self, state):
        if not self.bot.page: return
        is_checked = self.chk_gomoku_ui.isChecked()
        js = (
            f"window.useGomokuUI = {'true' if is_checked else 'false'};"
            "if(window.drawAllNumbers) window.drawAllNumbers();"
        )
        self.bot.pending_js.append(js)

    def change_overlay_opacity(self, val):
        self.lbl_opa.setText(f"{val}%")

    # Bảng quy đổi Cấp độ -> Thông số kỹ thuật (Max 55s vì luật VnCaro giới hạn 60s/nước)
    # VCF/VCT tìm thấy bẫy = đánh ngay (0.5s), chỉ MCTS mới dùng hết thời gian
    LEVEL_MAP = {
        1:  (2,   50,   "Tập sự"),
        2:  (3,   100,  "Nghiệp dư"),
        3:  (5,   200,  "Khá"),
        4:  (8,   300,  "Trung bình"),
        5:  (10,  400,  "Trung bình+"),
        6:  (15,  600,  "Mạnh"),
        7:  (20,  800,  "Rất mạnh"),
        8:  (30,  1200, "Cao thủ"),
        9:  (40,  2000, "Đại cao thủ"),
        10: (55,  5000, "Thần cờ (MAX)"),
    }

    def on_level_changed(self, lv):
        t, s, desc = self.LEVEL_MAP.get(lv, (10, 400, "?"))
        self.lbl_level_desc.setText(f"{desc} ({t}s, {s} sims)")
        self.update_params()

    def update_params(self, *args):
        lv = self.spin_level.value()
        t, s, _ = self.LEVEL_MAP.get(lv, (10, 400, ""))
        self.bot.play_as_x = self.rb_x.isChecked()
        self.bot.auto_farm = self.chk_autofarm.isChecked()
        self.bot.mcts_time = self.spin_delay.value()
        self.bot.simulations = self.spin_level.value() * 400
        self.bot.mode = "ai" if self.cb_mode.currentIndex() == 1 else "manual"

    def on_mode_changed(self, index):
        if index == 0: # Manual mode
            self.g2.setVisible(False)
            self.btn_go.setText("BẮT ĐẦU")
        else: # AI mode
            self.g2.setVisible(True)
            self.btn_go.setText("BẮT ĐẦU BOT")

    def toggle_bot(self):
        if not self.bot.active:
            self.update_params()
            self.bot.active = True
            if self.cb_mode.currentIndex() == 0:
                self.btn_go.setText("TẠM DỪNG")
            else:
                self.btn_go.setText("TẠM DỪNG BOT")
            self.btn_go.setStyleSheet("background:#dc3545;color:white;font-weight:bold;font-size:18px;padding:15px;")
            self.append_log("\n[▶] BOT HOẠT ĐỘNG!")
        else:
            self.bot_stopped()

    def bot_stopped(self):
        self.bot.active = False
        if self.cb_mode.currentIndex() == 0:
            self.btn_go.setText("BẮT ĐẦU")
        else:
            self.btn_go.setText("BẮT ĐẦU BOT")
        self.btn_go.setStyleSheet("background:#28a745;color:white;font-weight:bold;font-size:18px;padding:15px;")
        self.append_log("\n[⏸️] DỪNG BOT!")

    def append_log(self, text):
        if text == "CMD_FORCE_MANUAL":
            self.cb_mode.setCurrentIndex(0) # Chuyển sang Chơi thủ công
            return
        
        scrollbar = self.txt_log.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 5
        
        if text.startswith("\r"):
            text = text[1:].strip()
            cursor = self.txt_log.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
            last_text = cursor.selectedText()
            if "⏱️ Đang nghĩ" in last_text:
                cursor.removeSelectedText()
                cursor.insertText(text)
            else:
                self.txt_log.append(text)
        else:
            self.txt_log.append(text)
            
        if at_bottom:
            self.txt_log.moveCursor(QTextCursor.End)
            scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        self.bot.is_running = False
        self.bot.active = False
        self.bot.wait(4000)
        event.accept()

if __name__ == '__main__':
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    w = BotWindow()
    w.show()
    sys.exit(app.exec_())
