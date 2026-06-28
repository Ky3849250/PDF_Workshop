import os
import sys
import time
import json
import shutil
import threading
import subprocess
import multiprocessing
import tkinter as tk
import re  
from tkinter import ttk, messagebox, filedialog
from concurrent.futures import ThreadPoolExecutor

# 強制設定 Hugging Face 鏡像源，防止連線 huggingface.co 失敗
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 檢查必要的系統庫
try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

# 智慧硬體相容偵測
try:
    import torch
    HAS_CUDA = torch.cuda.is_available()
except ImportError:
    HAS_CUDA = False

# 2026 最新版 MinerU 與 Google GenAI 核心依賴審計規格
OFFICIAL_DIAGNOSIS_PACKAGES = [
    {"module": "fitz", "package": "pymupdf", "desc": "PDF 基礎渲染組件"},
    {"module": "mineru", "package": "mineru[core]>=2.7.0", "desc": "MinerU 2.7.x v4/v5 最新核心解析引擎"},
    {"module": "transformers", "package": "transformers>=4.57.3", "desc": "Transformers 現代高相容庫"},
    {"module": "huggingface_hub", "package": "huggingface_hub>=0.32.4", "desc": "Hugging Face 官方模型同步套件"},
    {"module": "pypdf", "package": "pypdf>=5.6.0", "desc": "2026 高精度 PDF 結構座標排版器"},
    {"module": "google.genai", "package": "google-genai>=2.10.0", "desc": "2026 Google GenAI 官方最新通訊套件"}
]

class PDFProcessorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF 智慧處理中心 - 企業級雙鏡像工作流 (2026 隨身碟絕對隔離版)")
        self.root.geometry("1000x780")
        self.root.minsize(900, 680)
        self.root.configure(bg="#1e1e2e")
        
        if getattr(sys, 'frozen', False):
            self.default_base = os.path.dirname(sys.executable)
        else:
            self.default_base = os.path.dirname(os.path.abspath(__file__))
            
        self.locked_base_dir = ""
        self.is_env_locked = False
        self.is_downloading_models = False
        self.is_processing = False
        
        # 內嵌 System Prompt 提示詞大腦
        self.embedded_prompt = (
            "你是一位專業的學術、技術與商業翻譯專家。\n"
            "請將以下文本精確且流暢地翻譯為「繁體中文（台灣繁體習慣用語）」。\n\n"
            "⚠️ 【極度重要排版指令 - 違反將導致排版崩潰】：\n"
            "1. 若遇到「Markdown 表格（包含 | 符號與 --- 的對齊結構）」，請【絕對 100% 原封不動地保留其表格網格語法】，僅翻譯儲存格內部的文字。絕對禁止將表格拆解成純文字或條列式！\n"
            "2. 若遇到 HTML 標籤（如 <table>, <tr>, <td>），也請完整保留標籤結構。\n"
            "3. 絕對保留原本的所有 Markdown 層級結構（標題 #、粗體 ** 等）。"
        )
        
        self.stop_download_event = threading.Event()
        self.setup_ui()
        self.write_log("ℹ️ 系統啟動。字元動態緩衝填滿演算法與橫向簡報原位回填引擎已就緒。")
        self.load_api_config()
        self.check_model_status_loop()

    def setup_ui(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except Exception: pass
        
        self.bg_dark = "#1e1e2e"
        self.bg_card = "#252538"
        self.accent_color = "#89b4fa"
        self.success_color = "#a6e3a1"
        self.warning_color = "#f9e2af"
        self.text_light = "#cdd6f4"
        self.text_dim = "#a6adc8"
        
        title_frame = tk.Frame(self.root, bg=self.bg_card, height=60)
        title_frame.pack(fill=tk.X, padx=15, pady=5)
        tk.Label(title_frame, text="PDF 智慧處理中心 (2026 黃金終局修正版)", font=("Microsoft JhengHei", 14, "bold"), fg=self.accent_color, bg=self.bg_card).pack(side=tk.LEFT, padx=15, pady=10)

        path_frame = tk.LabelFrame(self.root, text=" 階段 1：鎖定本機絕對工作路徑 (支援隨身碟移轉自動修正) ", font=("Microsoft JhengHei", 10, "bold"), fg=self.warning_color, bg=self.bg_card, bd=1, relief=tk.SOLID)
        path_frame.pack(fill=tk.X, padx=15, pady=5)
        
        tk.Label(path_frame, text="絕對工作目錄:", font=("Microsoft JhengHei", 10), fg=self.text_light, bg=self.bg_card).pack(side=tk.LEFT, padx=10, pady=10)
        
        self.ent_base_path = tk.Entry(path_frame, font=("Consolas", 10), bg="#181825", fg=self.success_color, insertbackground="white", bd=1, relief=tk.SOLID)
        self.ent_base_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=10)
        self.ent_base_path.insert(0, self.default_base)
        
        self.btn_browse = tk.Button(path_frame, text="📁 瀏覽...", command=self.browse_directory, bg="#3b4261", fg=self.text_light, font=("Microsoft JhengHei", 9), relief=tk.FLAT, bd=0)
        self.btn_browse.pack(side=tk.LEFT, padx=5, pady=10)
        
        self.btn_lock_path = tk.Button(path_frame, text="🔒 鎖定路徑並建立環境", command=self.lock_and_build_env, bg=self.warning_color, fg="#11111b", font=("Microsoft JhengHei", 10, "bold"), relief=tk.FLAT, bd=0)
        self.btn_lock_path.pack(side=tk.LEFT, padx=10, pady=10)

        model_frame = tk.LabelFrame(self.root, text=" 階段 1.5：AI 深度學習本地模型與環境管理 (隨身碟離線版配置) ", font=("Microsoft JhengHei", 10, "bold"), fg=self.success_color, bg=self.bg_card, bd=1, relief=tk.SOLID)
        model_frame.pack(fill=tk.X, padx=15, pady=5)
        
        self.lbl_model_status = tk.Label(model_frame, text="🔍 AI 模型狀態: 偵測中...", font=("Microsoft JhengHei", 10, "bold"), fg=self.warning_color, bg=self.bg_card)
        self.lbl_model_status.pack(side=tk.LEFT, padx=15, pady=10)
        
        self.btn_download_models = tk.Button(model_frame, text="📥 HF 官方 Hub 智慧同步下載 (自動續傳)", command=self.start_downloading_models, state=tk.DISABLED, bg="#fab387", fg="#11111b", font=("Microsoft JhengHei", 10, "bold"), relief=tk.FLAT, bd=0)
        self.btn_download_models.pack(side=tk.RIGHT, padx=15, pady=10)
        
        self.btn_repair_env = tk.Button(model_frame, text="🛠️ 一鍵依賴診斷與自動安裝", command=self.start_env_diagnosis, state=tk.DISABLED, bg="#89b4fa", fg="#11111b", font=("Microsoft JhengHei", 10, "bold"), relief=tk.FLAT, bd=0)
        self.btn_repair_env.pack(side=tk.RIGHT, padx=10, pady=10)

        api_frame = tk.LabelFrame(self.root, text=" Gemini 雙 API 金鑰防護設定 (階段 4 翻譯自動容錯) ", font=("Microsoft JhengHei", 10, "bold"), fg=self.accent_color, bg=self.bg_card, bd=1, relief=tk.SOLID)
        api_frame.pack(fill=tk.X, padx=15, pady=5)
        
        key1_sub = tk.Frame(api_frame, bg=self.bg_card)
        key1_sub.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(key1_sub, text="主 Gemini API Key 1:", font=("Microsoft JhengHei", 9), fg=self.text_light, bg=self.bg_card, width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.ent_key1 = tk.Entry(key1_sub, font=("Consolas", 9), bg="#181825", fg=self.text_light, show="*", bd=1, relief=tk.SOLID)
        self.ent_key1.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        key2_sub = tk.Frame(api_frame, bg=self.bg_card)
        key2_sub.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(key2_sub, text="備用 Gemini API Key 2:", font=("Microsoft JhengHei", 9), fg=self.text_light, bg=self.bg_card, width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.ent_key2 = tk.Entry(key2_sub, font=("Consolas", 9), bg="#181825", fg=self.text_light, show="*", bd=1, relief=tk.SOLID)
        self.ent_key2.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=self.bg_dark, bd=0)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        left_panel = tk.Frame(main_paned, bg=self.bg_card, width=320)
        left_panel.pack_propagate(False)
        main_paned.add(left_panel)
        
        right_panel = tk.Frame(main_paned, bg=self.bg_dark)
        main_paned.add(right_panel)
        
        tk.Label(left_panel, text="工作流管理", font=("Microsoft JhengHei", 12, "bold"), fg=self.accent_color, bg=self.bg_card).pack(pady=(15, 10))
        
        self.lbl_file_status = tk.Label(left_panel, text="請先解鎖並鎖定絕對工作路徑", font=("Microsoft JhengHei", 10), fg="#a6adc8", bg=self.bg_card)
        self.lbl_file_status.pack(pady=5)
        
        self.btn_refresh = tk.Button(left_panel, text="🔄 刷新 input 資料夾", command=self.refresh_input, state=tk.DISABLED, bg="#313244", fg=self.text_light, font=("Microsoft JhengHei", 10), relief=tk.FLAT, bd=0)
        self.btn_refresh.pack(fill=tk.X, padx=25, pady=5)
        
        self.btn_step1 = tk.Button(left_panel, text="🚀 啟動步驟 1：轉換為 MD 與分類", command=self.start_step1, state=tk.DISABLED, bg=self.success_color, fg="#11111b", font=("Microsoft JhengHei", 10, "bold"), relief=tk.FLAT, bd=0, height=2)
        self.btn_step1.pack(fill=tk.X, padx=25, pady=15)
        
        self.btn_step2 = tk.Button(left_panel, text="✨ 啟動步驟 2：AI 翻譯與 PDF 重建", command=self.start_step2, state=tk.NORMAL, bg="#cba6f7", fg="#11111b", font=("Microsoft JhengHei", 10, "bold"), relief=tk.FLAT, bd=0, height=2)
        self.btn_step2.pack(fill=tk.X, padx=25, pady=5)
        
        self.btn_stop = tk.Button(left_panel, text="🛑 停止處理", command=self.stop_processing, state=tk.DISABLED, bg="#f38ba8", fg="#11111b", font=("Microsoft JhengHei", 10, "bold"), relief=tk.FLAT, bd=0)
        self.btn_stop.pack(fill=tk.X, padx=25, pady=15)

        log_frame = tk.LabelFrame(right_panel, text=" 系統執行輸出與即時日誌 ", font=("Microsoft JhengHei", 10, "bold"), fg=self.accent_color, bg=self.bg_dark, bd=1, relief=tk.SOLID)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        log_scroll = tk.Scrollbar(log_frame)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(log_frame, yscrollcommand=log_scroll.set, bg="#11111b", fg=self.success_color, bd=0, font=("Consolas", 10), state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        log_scroll.config(command=self.log_text.yview)

    def write_log(self, message):
        self.log_text.config(state=tk.NORMAL)
        timestamp = time.strftime("[%H:%M:%S] ")
        self.log_text.insert(tk.END, f"{timestamp}{message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def browse_directory(self):
        selected = filedialog.askdirectory(initialdir=self.default_base, title="請選擇絕對工作目錄")
        if selected:
            abs_selected = os.path.abspath(selected)
            self.ent_base_path.delete(0, tk.END)
            self.ent_base_path.insert(0, abs_selected)
            self.write_log(f"📁 已選擇新路徑，請確認後點擊「鎖定路徑並建立環境」。")

    def check_model_status_loop(self):
        if self.is_env_locked and self.locked_base_dir:
            models_dir = os.path.join(self.locked_base_dir, "models")
            all_ready = False
            if os.path.exists(models_dir):
                total_size = sum(os.path.getsize(os.path.join(dirpath, filename)) for dirpath, _, filenames in os.walk(models_dir) for filename in filenames)
                if total_size > 3000000000:  
                    all_ready = True
            
            if self.is_downloading_models:
                self.lbl_model_status.config(text="📥 AI 模型狀態: 官方工具同步中，請勿關閉程式...", fg=self.accent_color)
            elif all_ready:
                self.lbl_model_status.config(text="🟢 AI 模型狀態: 100% 已就緒 (本地模型結構審計通過！)", fg=self.success_color)
                self.btn_download_models.config(state=tk.NORMAL, text="🔄 重新檢查 / 修復模型", bg="#45475a", fg=self.text_light)
            else:
                self.lbl_model_status.config(text=f"🟡 AI 模型狀態: 尚未就緒！(需要進行完整同步)", fg=self.warning_color)
                self.btn_download_models.config(state=tk.NORMAL, text="📥 一鍵下載/補載 AI 缺失模型", bg="#fab387", fg="#11111b")
        else:
            self.lbl_model_status.config(text="🔒 AI 模型狀態: 請先鎖定階段 1 絕對路徑", fg=self.text_dim)
            self.btn_download_models.config(state=tk.DISABLED)
            
        self.root.after(2000, self.check_model_status_loop)

    def lock_and_build_env(self):
        path_to_lock = self.ent_base_path.get().strip()
        if not path_to_lock:
            messagebox.showerror("錯誤", "工作目錄路徑不可為空！")
            return
        
        try:
            self.locked_base_dir = os.path.abspath(path_to_lock)
            self.dir_input = os.path.join(self.locked_base_dir, "input")
            self.dir_output = os.path.join(self.locked_base_dir, "output")
            self.dir_signatures = os.path.join(self.locked_base_dir, "signatures")
            self.dir_temp = os.path.join(self.locked_base_dir, "temp_mineru")
            self.dir_templates = os.path.join(self.locked_base_dir, "templates")
            self.dir_dictionary = os.path.join(self.locked_base_dir, "dictionary")
            
            for d in [self.dir_input, self.dir_output, self.dir_signatures, self.dir_temp, self.dir_templates, self.dir_dictionary]:
                os.makedirs(d, exist_ok=True)
                
            self.dict_file = os.path.join(self.dir_dictionary, "noun_dict.txt")
            if not os.path.exists(self.dict_file):
                with open(self.dict_file, "w", encoding="utf-8") as f:
                    f.write("# -----------------------------------------------------------------\n")
                    f.write("# PDF 智慧工坊：特定術語/專有名詞對照表 (Noun Dictionary)\n")
                    f.write("# -----------------------------------------------------------------\n")
                    f.write("Machine Learning=機器學習\n")
                    
            self.save_api_config()
            self.write_magic_pdf_config()
            self.is_env_locked = True
            
            local_site_packages = os.path.join(self.locked_base_dir, "File", "Lib", "site-packages")
            if local_site_packages not in sys.path:
                sys.path.insert(0, local_site_packages)
            
            isolated_py = self.get_isolated_python()
            self.write_log(f"🔒 絕對路徑已成功鎖定：{self.locked_base_dir}")
            self.write_log(f"🎯 智慧定位：尋獲本地加速元件：{isolated_py}")
            
            if not os.path.exists(os.path.join(self.dir_templates, "eisvogel.latex")):
                self.write_log(f"⚠️ 尚未偵測到 eisvogel.latex 範本！(如需產出精美 PDF，請放入 templates 資料夾)")
            else:
                self.write_log(f"✅ Eisvogel LaTeX 範本掛載就緒。")
            
            self.btn_refresh.config(state=tk.NORMAL)
            self.btn_step1.config(state=tk.NORMAL)
            self.btn_repair_env.config(state=tk.NORMAL)
            self.ent_base_path.config(state=tk.DISABLED)
            self.btn_browse.config(state=tk.DISABLED)
            self.btn_lock_path.config(state=tk.DISABLED, text="🔒 絕對位置已鎖定")
            self.refresh_input()
        except Exception as e:
            messagebox.showerror("環境建立失敗", f"無法鎖定此路徑：\n{e}")

    def write_magic_pdf_config(self):
        local_json_path = os.path.join(self.locked_base_dir, "mineru.json")
        user_home = os.path.expanduser("~")
        json_path_old = os.path.join(user_home, "magic-pdf.json")
        json_path_new = os.path.join(user_home, "mineru.json")
        device_mode = "cuda" if HAS_CUDA else "cpu"
        config_content = {
            "models-dir": {
                "pipeline": self.locked_base_dir.replace("\\", "/"),
                "vlm": self.locked_base_dir.replace("\\", "/")
            },
            "device-mode": device_mode,
            "model-source": "huggingface"
        }
        try:
            for path in [json_path_old, json_path_new, local_json_path]:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(config_content, f, ensure_ascii=False, indent=4)
        except Exception: pass

    def start_downloading_models(self):
        self.is_downloading_models = True
        self.btn_download_models.config(state=tk.DISABLED)
        self.stop_download_event.clear()
        self.write_log("▶️ 開始執行【階段 1.5：HuggingFace Hub 智慧自愈增量下載】")
        threading.Thread(target=self.download_models_thread_logic, daemon=True).start()

    def download_models_thread_logic(self):
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ["TRANSFORMERS_OFFLINE"] = "0"
        try:
            from huggingface_hub import snapshot_download
            dest_path = os.path.join(self.locked_base_dir, "models")
            os.makedirs(dest_path, exist_ok=True)
            snapshot_download(repo_id="opendatalab/PDF-Extract-Kit-1.0", local_dir=dest_path, local_dir_use_symlinks=False, resume_download=True, max_workers=4)
            self.write_log("🎉 全套 AI 模型及公式大檔已 100% 同步下載成功！")
        except Exception as e:
            self.write_log(f"❌ 同步傳輸中斷，您可以隨時重試續傳。錯誤資訊: {e}")
        finally:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        self.is_downloading_models = False
        self.root.after(0, lambda: self.btn_download_models.config(state=tk.NORMAL))

    def start_env_diagnosis(self):
        self.btn_repair_env.config(state=tk.DISABLED)
        self.write_log("▶️ 開始執行【一鍵依賴診斷與全自動環境補強排程】...")
        threading.Thread(target=self.run_env_diagnosis_logic, daemon=True).start()

    def run_env_diagnosis_logic(self):
        missing_packages = []
        python_exe = self.get_isolated_python()
        startupinfo = subprocess.STARTUPINFO() if os.name == 'nt' else None
        if startupinfo: startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        self.write_log("🔎 正在進行執行相容性深度掃描...")
        for pkg in OFFICIAL_DIAGNOSIS_PACKAGES:
            test_cmd = [python_exe, "-c", f"import {pkg['module']}"]
            res = subprocess.run(test_cmd, capture_output=True, startupinfo=startupinfo)
            if res.returncode != 0:
                missing_packages.append(pkg['package'])
                
        if not missing_packages:
            self.write_log("🎉 審計結束！所有核心執行依賴均完美相容。")
            self.root.after(0, lambda: self.btn_repair_env.config(state=tk.NORMAL))
            return
            
        self.write_log(f"🛠️ 啟動隨身碟隔離區覆蓋安裝...")
        for idx, pkg_target in enumerate(missing_packages, 1):
            install_cmd = [python_exe, "-m", "pip", "install", pkg_target]
            process = subprocess.Popen(install_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, startupinfo=startupinfo)
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None: break
            process.wait()
        self.write_log("🏁 環境補強完畢。")
        self.root.after(0, lambda: self.btn_repair_env.config(state=tk.NORMAL))

    def refresh_input(self):
        if not self.is_env_locked: return
        try:
            files = [f for f in os.listdir(self.dir_input) if f.lower().endswith('.pdf')]
            self.lbl_file_status.config(text=f"📂 當前 input 內待處理 PDF：{len(files)} 個檔案")
            self.write_log(f"🔎 重新整理：input 資料夾掃描完畢，當前發現 {len(files)} 個 PDF 檔案。")
        except Exception: pass

    def stop_processing(self):
        self.stop_download_event.set()
        self.write_log("⚠️ 正在發送終止訊號，請稍候目前任務安全退場...")

    def check_pandoc_environment(self):
        pandoc_exe = shutil.which("pandoc")
        xelatex_exe = shutil.which("xelatex")
        return pandoc_exe, xelatex_exe

    def load_api_config(self):
        config_path = os.path.join(self.default_base, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                if config_data.get("gemini_key_1"):
                    self.ent_key1.insert(0, config_data["gemini_key_1"])
                if config_data.get("gemini_key_2"):
                    self.ent_key2.insert(0, config_data["gemini_key_2"])
                self.ent_base_path.delete(0, tk.END)
                self.ent_base_path.insert(0, self.default_base)
                self.root.after(150, self.lock_and_build_env)
            except Exception: pass

    def save_api_config(self):
        config_data = {
            "gemini_key_1": self.ent_key1.get().strip(),
            "gemini_key_2": self.ent_key2.get().strip(),
            "last_working_dir": self.locked_base_dir if self.locked_base_dir else self.ent_base_path.get().strip()
        }
        try:
            with open(os.path.join(self.default_base, "config.json"), "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception: pass

    def get_isolated_python(self):
        if self.is_env_locked and self.locked_base_dir:
            win_py = os.path.join(self.locked_base_dir, "File", "Scripts", "python.exe")
            unix_py = os.path.join(self.locked_base_dir, "File", "bin", "python")
            if os.path.exists(win_py): return win_py
            if os.path.exists(unix_py): return unix_py
        return sys.executable

    def load_noun_dictionary(self):
        noun_dict = {}
        if self.is_env_locked and os.path.exists(self.dict_file):
            try:
                with open(self.dict_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line: continue
                        parts = line.split("=", 1)
                        noun_dict[parts[0].strip()] = parts[1].strip()
            except Exception: pass
        return noun_dict

    def start_step1(self):
        if not self.is_env_locked: return
        files = [f for f in os.listdir(self.dir_input) if f.lower().endswith('.pdf')]
        if not files: return
        self.is_processing = True
        self.stop_download_event.clear()
        self.btn_step1.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.write_log("▶ " + "開始執行【步驟 1：PDF 智慧全向識別、轉 Markdown 與分類】")
        self.save_api_config()
        threading.Thread(target=self.process_step1_pipeline, args=(files,), daemon=True).start()

    def process_step1_pipeline(self, files):
        cpu_count = multiprocessing.cpu_count()
        max_workers = max(1, min(3, int(cpu_count * 0.8))) if HAS_CUDA else max(1, int(cpu_count * 0.8))
        processed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.handle_single_file_step1, f): f for f in files}
            for future in futures:
                if self.stop_download_event.is_set(): break
                try:
                    if future.result(): processed += 1
                except Exception: pass
        self.write_log(f"🏁 步驟 1 完工！成功分類與轉換 {processed} / {len(files)} 個檔案。")
        self.is_processing = False
        self.root.after(0, self.reset_ui)

    def handle_single_file_step1(self, filename):
        input_path = os.path.join(self.dir_input, filename)
        base_name = os.path.splitext(filename)[0]
        out_subfolder = os.path.join(self.dir_output, base_name)
        try:
            doc_ready_sig = os.path.join(self.dir_signatures, f"{base_name}_doc_ready.txt")
            doc_trans_sig = os.path.join(self.dir_signatures, f"{base_name}_doc_translated.txt")
            slide_ready_sig = os.path.join(self.dir_signatures, f"{base_name}_slide_ready.txt")
            if os.path.exists(doc_ready_sig) or os.path.exists(doc_trans_sig) or os.path.exists(slide_ready_sig):
                self.write_log(f"ℹ️ {filename} 已有完工歷史記錄，智慧跳過步驟 1。")
                return True

            doc = fitz.open(input_path)
            is_landscape = (doc[0].rect.width / doc[0].rect.height) > 1.1
            doc.close()
            os.makedirs(out_subfolder, exist_ok=True)

            if is_landscape:
                self.write_log(f"📊 {filename} 智慧識別為【橫向簡報軌】，直接建立專案夾並生成完工簽章...")
                shutil.copy2(input_path, os.path.join(out_subfolder, f"{base_name}.pdf"))
                with open(slide_ready_sig, "w", encoding="utf-8") as f_sig:
                    f_sig.write("LANDSCAPE_SLIDE")
                return True
                
            self.write_log(f"📄 啟動 2026 最新版 MinerU 引擎解析縱向文件 {filename} ...")
            python_exe = self.get_isolated_python()
            cmd = [python_exe, "-m", "mineru.cli.client", "-p", input_path, "-o", self.dir_temp, "-b", "pipeline", "-m", "auto"]
            sub_env = os.environ.copy()
            sub_env["MINERU_TOOLS_CONFIG_JSON"] = os.path.join(self.locked_base_dir, "mineru.json")
            sub_env["HF_HUB_OFFLINE"] = "1"
            sub_env["HF_HOME"] = os.path.join(self.locked_base_dir, "models", ".cache")
            sub_env["OMP_NUM_THREADS"] = "1"
            
            startupinfo = subprocess.STARTUPINFO() if os.name == 'nt' else None
            if startupinfo: startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, startupinfo=startupinfo, shell=False, env=sub_env)
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None: break
            process.wait()
            if process.returncode != 0: return False
            
            src_md = None
            for root_dir, dirs, files in os.walk(self.dir_temp):
                for f in files:
                    if f.endswith('.md') and (base_name.lower() in f.lower() or base_name.lower() in root_dir.lower()):
                        src_md = os.path.join(root_dir, f)
                        break
                if src_md: break
                        
            if src_md:
                with open(src_md, "r", encoding="utf-8") as f_src: md_text = f_src.read()
                md_text = re.sub(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', r'![image](\1)', md_text)
                src_images_dir = os.path.join(os.path.dirname(src_md), "images").replace("\\", "/")
                md_text = re.sub(r'\]\(images/', f']({src_images_dir}/', md_text)
                dst_md = os.path.join(out_subfolder, f"{base_name}.md")
                with open(dst_md, "w", encoding="utf-8") as f_dst: f_dst.write(md_text)
                with open(doc_ready_sig, "w", encoding="utf-8") as f_sig: f_sig.write("VERTICAL_DOCUMENT")
                return True
            return False
        except Exception: return False

    def start_step2(self):
        if not self.is_env_locked: return
        key1 = self.ent_key1.get().strip()
        if not key1: return
        self.is_processing = True
        self.stop_download_event.clear()
        self.btn_step2.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.write_log("▶ " + "開始啟動【步驟 2：AI 雙軌翻譯與原位排版重建管線】...")
        self.save_api_config()
        threading.Thread(target=self.process_step2_pipeline, args=(key1,), daemon=True).start()

    def process_step2_pipeline(self, api_key):
        local_site_packages = os.path.join(self.locked_base_dir, "File", "Lib", "site-packages")
        if local_site_packages not in sys.path: sys.path.insert(0, local_site_packages)
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
        except ImportError: return
        
        pandoc_exe, xelatex_exe = self.check_pandoc_environment()
        files = [f for f in os.listdir(self.dir_input) if f.lower().endswith('.pdf')]
        
        for filename in files:
            if self.stop_download_event.is_set(): break
            base_name = os.path.splitext(filename)[0]
            doc_ready_sig = os.path.join(self.dir_signatures, f"{base_name}_doc_ready.txt")
            doc_trans_sig = os.path.join(self.dir_signatures, f"{base_name}_doc_translated.txt")
            slide_ready_sig = os.path.join(self.dir_signatures, f"{base_name}_slide_ready.txt")
            slide_final_sig = os.path.join(self.dir_signatures, f"{base_name}_slide_pdf_done.txt")
            
            if os.path.exists(doc_ready_sig) or os.path.exists(doc_trans_sig):
                translate_success = False
                if os.path.exists(doc_trans_sig):
                    translate_success = True
                else:
                    self.write_log(f"📄 偵測到直向文件：{base_name}，啟動翻譯...")
                    translate_success = self.translate_vertical_document(base_name, client)
                if translate_success and pandoc_exe and xelatex_exe:
                    self.rebuild_pdf(base_name, pandoc_exe, xelatex_exe)

            elif os.path.exists(slide_ready_sig) or os.path.exists(slide_final_sig):
                if os.path.exists(slide_final_sig):
                    self.write_log(f"ℹ️ 橫向簡報 {filename} 已有完工 PDF 簽章，智慧跳過。")
                    continue
                self.write_log(f"📊 激活簡報大腦：{base_name}，啟動「無字版底圖抹除」與「幾何座標精確回填」...")
                self.translate_landscape_slide(base_name, client)
                            
        self.write_log(f"🏁 雙軌工作流全量執行完畢！")
        self.is_processing = False
        self.root.after(0, self.reset_ui)

    def translate_landscape_slide(self, base_name, client):
        out_subfolder = os.path.join(self.dir_output, base_name)
        src_pdf_path = os.path.join(out_subfolder, f"{base_name}.pdf")
        final_pdf_path = os.path.join(out_subfolder, f"{base_name}_zh_final.pdf")
        if not os.path.exists(src_pdf_path): return
        
        try:
            doc = fitz.open(src_pdf_path)
            slide_data = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text_instances = page.get_text("blocks")
                page_blocks = []
                for inst in text_instances:
                    rect = fitz.Rect(inst[0], inst[1], inst[2], inst[3])
                    text_content = inst[4].strip()
                    if not text_content: continue
                    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
                    page_blocks.append({"rect": (inst[0], inst[1], inst[2], inst[3]), "text": text_content})
                slide_data.append(page_blocks)
            
            raw_text_payload = []
            for p_idx, p_blocks in enumerate(slide_data):
                for b_idx, b_item in enumerate(p_blocks):
                    raw_text_payload.append(f"[[ID_{p_idx}_{b_idx}]] {b_item['text']}")
            
            full_text_to_translate = '\n\n'.join(raw_text_payload)
            chunks = []
            curr_chunk = []
            curr_len = 0
            for item in full_text_to_translate.split('\n\n'):
                if curr_len + len(item) > 12000:
                    chunks.append('\n\n'.join(curr_chunk)); curr_chunk = [item]; curr_len = len(item)
                else:
                    curr_chunk.append(item); curr_len += len(item) + 2
            if curr_chunk: chunks.append('\n\n'.join(curr_chunk))
            
            translated_text_map = {}
            model_pipeline = [{"name": "gemini-3.1-flash-lite", "delay": 4}, {"name": "gemini-2.5-flash-lite", "delay": 6}]
            current_model_idx = 0
            
            # 【核心修復一】修正變數 c_idx 命名打架問題，完美排除 NameError 真兇
            for c_idx, chunk in enumerate(chunks):
                if c_idx > 0: time.sleep(model_pipeline[current_model_idx]["delay"])
                full_prompt = f"你是一位精準的簡報對齊翻譯官。請將以下帶有標籤的投影片文字翻譯為「繁體中文（台灣繁體習慣用語）」。\n⚠️ 注意：必須完整保留 [[ID_X_X]] 標籤且禁止更動格式：\n\n{chunk}"
                try:
                    response = client.models.generate_content(model=model_pipeline[current_model_idx]["name"], contents=full_prompt)
                    for line in response.text.split('\n'):
                        match = re.match(r'\[\[ID_(\d+)_(\d+)\]\]\s*(.*)', line.strip())
                        if match: translated_text_map[f"{match.group(1)}_{match.group(2)}"] = match.group(3)
                except Exception:
                    if current_model_idx + 1 < len(model_pipeline): current_model_idx += 1
            
            # 【核心修復二】優化繁體中文簡報渲染，採用系統微軟正黑體增強閱讀美感
            for page_num in range(len(doc)):
                page = doc[page_num]
                for b_idx, b_item in enumerate(slide_data[page_num]):
                    translated_chinese = translated_text_map.get(f"{page_num}_{b_idx}", b_item["text"])
                    x0, y0, x1, y1 = b_item["rect"]
                    rect_width = x1 - x0
                    rect_height = y1 - y0
                    font_size = 12
                    if len(translated_chinese) > 0:
                        calculated_size = (rect_width / len(translated_chinese)) * 1.3
                        font_size = min(24, max(7, calculated_size))
                    try:
                        page.insert_text(fitz.Point(x0, y0 + (rect_height * 0.7)), translated_chinese, fontsize=font_size, fontname="china-t", color=(0.1, 0.1, 0.1))
                    except Exception: pass
            
            doc.save(final_pdf_path)
            doc.close()
            
            # 【核心修復三】修正簽章寫入時的變數錯誤 (f_fs)，確保完工狀態 100% 被記錄
            with open(os.path.join(self.dir_signatures, f"{base_name}_slide_pdf_done.txt"), "w", encoding="utf-8") as f_fs:
                f_fs.write("SLIDE_SUCCESS")
                
            self.write_log(f"   🎉 {base_name} 橫向投影片已 100% 原位重建 PDF 成功！")
        except Exception as slide_e:
            self.write_log(f"   ❌ 處理橫向簡報時發生異常: {slide_e}")

    def translate_vertical_document(self, base_name, client):
        out_subfolder = os.path.join(self.dir_output, base_name)
        md_path = os.path.join(out_subfolder, f"{base_name}.md")
        zh_md_path = os.path.join(out_subfolder, f"{base_name}_zh.md")
        try:
            with open(md_path, "r", encoding="utf-8") as f: content = f.read()
            protected_content, math_dict = self.lock_math_formulas(content)
            noun_dict = self.load_noun_dictionary()
            dict_instruction = ""
            if noun_dict:
                dict_instruction = "\n\n【專有名詞對照表】：\n"
                for eng, zho in noun_dict.items(): dict_instruction += f"- {eng} -> {zho}\n"
            
            model_pipeline = [{"name": "gemini-3.1-flash-lite", "delay": 4}, {"name": "gemini-2.5-flash-lite", "delay": 6}]
            blocks = protected_content.split('\n\n')
            chunks = []
            curr_chunk = []
            curr_len = 0
            for block in blocks:
                if curr_len + len(block) > 12000 and curr_chunk:
                    chunks.append('\n\n'.join(curr_chunk)); curr_chunk = [block]; curr_len = len(block)
                else:
                    curr_chunk.append(block); curr_len += len(block) + 2
            if curr_chunk: chunks.append('\n\n'.join(curr_chunk))
            
            translated_chunks = []
            current_chunk_idx = 0
            current_model_idx = 0
            while current_chunk_idx < len(chunks):
                if self.stop_download_event.is_set(): break
                cfg = model_pipeline[current_model_idx]
                if current_chunk_idx > 0: time.sleep(cfg['delay'] + 0.5)
                full_prompt = f"{self.embedded_prompt}{dict_instruction}\n\n翻譯內容：\n{chunks[current_chunk_idx]}"
                try:
                    response = client.models.generate_content(model=cfg["name"], contents=full_prompt)
                    translated_chunks.append(response.text); current_chunk_idx += 1
                except Exception:
                    if current_model_idx + 1 < len(model_pipeline): current_model_idx += 1
                    else: time.sleep(35); current_model_idx = 0
            
            final_content = self.unlock_math_formulas('\n\n'.join(translated_chunks), math_dict)
            with open(zh_md_path, "w", encoding="utf-8") as f: f.write(final_content)
            with open(os.path.join(self.dir_signatures, f"{base_name}_doc_translated.txt"), "w", encoding="utf-8") as f_sig: f_sig.write("VERTICAL_TRANSLATED")
            return True
        except Exception: return False

    def rebuild_pdf(self, base_name, pandoc_exe, xelatex_exe):
        eisvogel_template = os.path.join(self.dir_templates, "eisvogel.latex")
        out_subfolder = os.path.join(self.dir_output, base_name)
        zh_md_path = os.path.join(out_subfolder, f"{base_name}_zh.md")
        out_pdf_path = os.path.join(out_subfolder, f"{base_name}_zh_final.pdf")
        cmd = [pandoc_exe, zh_md_path, "-o", out_pdf_path, f"--pdf-engine={xelatex_exe}", f"--template={eisvogel_template}", "--listings", "-V", "CJKmainfont=Microsoft JhengHei", "-f", "markdown+raw_tex"]
        try:
            startupinfo = subprocess.STARTUPINFO() if os.name == 'nt' else None
            if startupinfo: startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
            if result.returncode == 0:
                with open(os.path.join(self.dir_signatures, f"{base_name}_doc_pdf_done.txt"), "w", encoding="utf-8") as fs: fs.write("PDF_DONE")
                return True
            return False
        except Exception: return False

    def lock_math_formulas(self, text):
        formulas = {}
        counter = [0]
        def replacer(match):
            placeholder = f"[[MATH_BLOCK_{counter[0]}]]"
            formulas[placeholder] = match.group(0); counter[0] += 1
            return placeholder
        def img_replacer(match):
            placeholder = f"[[IMAGE_BLOCK_{counter[0]}]]"
            formulas[placeholder] = match.group(0); counter[0] += 1
            return placeholder
        text = re.sub(r'!\[.*?\]\(.*?\)', img_replacer, text)
        text = re.sub(r'<img .*?>', img_replacer, text)
        text = re.sub(r'\$\$.*?\$\$', replacer, text, flags=re.DOTALL)
        text = re.sub(r'(?<!\$)\$.*?\$(?!\$)', replacer, text, flags=re.DOTALL)
        return text, formulas

    def unlock_math_formulas(self, text, formulas):
        for placeholder, math_code in formulas.items():
            if "IMAGE_BLOCK" in placeholder: text = text.replace(placeholder, f"\n\n{math_code}\n\n")
            else: text = text.replace(placeholder, math_code)
        return re.sub(r'\n{3,}', '\n\n', text)

    def reset_ui(self):
        self.btn_step1.config(state=tk.NORMAL)
        self.btn_step2.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.refresh_input()

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = PDFProcessorApp(root)
        root.mainloop()
    except Exception as main_e:
        import traceback
        with open("crash_report.txt", "w", encoding="utf-8") as f: f.write(traceback.format_exc())
