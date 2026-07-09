import os
import sys
import platform
import uuid
import hashlib
import threading
import time
import importlib.metadata
from datetime import datetime
import subprocess
from pathlib import Path

class Inspector:
    _instance = None
    _lock = None

    def __new__(cls):
        import threading
        if cls._lock is None:
            cls._lock = threading.Lock()
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Inspector, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.cache = {}
        self.cache_ttl = 3600
        self.last_examination = 0
        self.machine_id = None
        self._colab_auth_triggered = False
        self.home_dir = Path.home()
        self.project_dir = self._get_project_dir()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.id_dir = self.project_dir /'id'
        self.id_dir.mkdir(parents=True, exist_ok=True)
        self.api_key_path = self.project_dir /"api_key.json"
        self.user_info_path = self.project_dir /"user.json"
        self.device_id_path = self.project_dir /"device.id"
        self.machine_id_path = self.id_dir /"machine_id.txt"
        self.examine()

    def _get_home_dir(self) -> Path:
        return Path.home()

    def _get_project_dir(self) -> Path:
        home_dir = Path.home() /".vnstock"
        if (home_dir /"api_key.json").exists():
            return home_dir
        is_colab ='google.colab' in sys.modules
        if is_colab:
            drive_path = Path('/content/drive/MyDrive/.vnstock')
            if drive_path.exists():
                return drive_path
            if Path('/content').exists():
                return home_dir
        try:
            from vnstock.core.config.ggcolab import get_vnstock_directory
            legacy_dir = get_vnstock_directory()
            if legacy_dir.exists():
                return legacy_dir
        except (ImportError, Exception):
            pass
        return home_dir

    def examine(self, force_refresh=False):
        current_time = time.time()
        if not force_refresh and (current_time - self.last_examination) < self.cache_ttl:
            return self.cache
        info = {
"timestamp": datetime.now().isoformat(),
"python_version": platform.python_version(),
"os_name": platform.system(),
"platform": platform.platform()
        }
        info["machine_id"] = self.fingerprint()
        try:
            import importlib.util
            ipython_spec = importlib.util.find_spec("IPython")
            if ipython_spec:
                from IPython import get_ipython
                ipython = get_ipython()
                if ipython is not None:
                    info["environment"] ="jupyter"
                    if'google.colab' in sys.modules:
                        info["hosting_service"] ="colab"
                    elif'KAGGLE_KERNEL_RUN_TYPE' in os.environ:
                        info["hosting_service"] ="kaggle"
                    else:
                        info["hosting_service"] ="local_jupyter"
                elif sys.stdout.isatty():
                    info["environment"] ="terminal"
                else:
                    info["environment"] ="script"
            elif sys.stdout.isatty():
                info["environment"] ="terminal"
            else:
                info["environment"] ="script"
        except:
            info["environment"] ="unknown"
        try:
            import psutil
            info["cpu_count"] = os.cpu_count()
            memory_total = psutil.virtual_memory().total
            info["memory_gb"] = round(memory_total / (1024**3), 1)
        except Exception:
            pass
        is_colab ='google.colab' in sys.modules
        if is_colab:
            info["is_colab"] = True
            self.detect_colab_with_delayed_auth()
        try:
            info["commercial_usage"] = self.enhanced_commercial_detection()
            info["project_context"] = self.analyze_project_structure()
            info["git_info"] = self.analyze_git_info()
            info["usage_pattern"] = self.detect_usage_pattern()
            info["dependencies"] = self.analyze_dependencies()
            info["vibe_coding_maturity"] = self.analyze_vibe_coding_maturity()
        except Exception as e:
            info["detection_error"] = str(e)
        self.cache = info
        self.last_examination = current_time
        return info

    def fingerprint(self):
        if self.machine_id:
            return self.machine_id
        env_device_id = os.environ.get('VNSTOCK_DEVICE_ID')
        if env_device_id:
            self.machine_id = env_device_id
            return self.machine_id
        if self.device_id_path.exists():
            try:
                self.machine_id = self.device_id_path.read_text().strip()
                if self.machine_id:
                    return self.machine_id
            except Exception:
                pass
        if self.user_info_path.exists():
            try:
                with open(self.user_info_path,'r') as f:
                    import json
                    data = json.load(f)
                    self.machine_id = data.get('device_id') or data.get('uuid')
                    if self.machine_id:
                        return self.machine_id
            except Exception:
                pass
        try:
            from vnai.scope.device import device_registry
            registry = device_registry.get_registry()
            if registry and registry.get('device_id'):
                self.machine_id = registry['device_id']
                return self.machine_id
        except Exception:
            pass
        if self.machine_id_path.exists():
            try:
                with open(self.machine_id_path,"r") as f:
                    self.machine_id = f.read().strip()
                    return self.machine_id
            except Exception:
                pass
        is_colab = self.detect_colab_with_delayed_auth()
        try:
            system_info = platform.node() + platform.platform() + platform.machine()
            self.machine_id = hashlib.md5(system_info.encode()).hexdigest()
        except Exception:
            self.machine_id = str(uuid.uuid4())
        return self.machine_id

    def detect_hosting(self):
        hosting_markers = {
"COLAB_GPU":"Google Colab",
"KAGGLE_KERNEL_RUN_TYPE":"Kaggle",
"BINDER_SERVICE_HOST":"Binder",
"CODESPACE_NAME":"GitHub Codespaces",
"STREAMLIT_SERVER_HEADLESS":"Streamlit Cloud",
"CLOUD_SHELL":"Cloud Shell"
        }
        for env_var, host_name in hosting_markers.items():
            if env_var in os.environ:
                return host_name
        if'google.colab' in sys.modules:
            return"Google Colab"
        return"local"

    def detect_commercial_usage(self):
        commercial_indicators = {
"env_domains": [".com",".io",".co","enterprise","corp","inc"],
"file_patterns": ["invoice","payment","customer","client","product","sale"],
"env_vars": ["COMPANY","BUSINESS","ENTERPRISE","CORPORATE"],
"dir_patterns": ["company","business","enterprise","corporate","client"]
        }
        env_values =" ".join(os.environ.values()).lower()
        domain_match = any(domain in env_values for domain in commercial_indicators["env_domains"])
        env_var_match = any(var in os.environ for var in commercial_indicators["env_vars"])
        current_dir = os.getcwd().lower()
        dir_match = any(pattern in current_dir for pattern in commercial_indicators["dir_patterns"])
        try:
            files = [f.lower() for f in os.listdir() if os.path.isfile(f)]
            file_match = any(any(pattern in f for pattern in commercial_indicators["file_patterns"]) for f in files)
        except:
            file_match = False
        indicators = [domain_match, env_var_match, dir_match, file_match]
        commercial_probability = sum(indicators) / len(indicators)
        return {
"likely_commercial": commercial_probability > 0.3,
"commercial_probability": commercial_probability,
"commercial_indicators": {
"domain_match": domain_match,
"env_var_match": env_var_match,
"dir_match": dir_match,
"file_match": file_match
            }
        }

    def scan_packages(self):
        package_groups = {
"vnstock_family": [
"vnstock",
"vnstock3",
"vnstock_ezchart",
"vnstock_data_pro",
"vnstock_market_data_pipeline",
"vnstock_ta",
"vnii",
"vnai"
            ],
"analytics": [
"openbb",
"pandas_ta"
            ],
"static_charts": [
"matplotlib",
"seaborn",
"altair"
            ],
"dashboard": [
"streamlit",
"voila",
"panel",
"shiny",
"dash"
            ],
"interactive_charts": [
"mplfinance",
"plotly",
"plotline",
"bokeh",
"pyecharts",
"highcharts-core",
"highcharts-stock",
"mplchart"
            ],
"datafeed": [
"yfinance",
"alpha_vantage",
"pandas-datareader",
"investpy"
            ],
"official_api": [
"ssi-fc-data",
"ssi-fctrading"
            ],
"risk_return": [
"pyfolio",
"empyrical",
"quantstats",
"financetoolkit"
            ],
"machine_learning": [
"scipy",
"sklearn",
"statsmodels",
"pytorch",
"tensorflow",
"keras",
"xgboost"
            ],
"indicators": [
"stochastic",
"talib",
"tqdm",
"finta",
"financetoolkit",
"tulipindicators"
            ],
"backtesting": [
"vectorbt",
"backtesting",
"bt",
"zipline",
"pyalgotrade",
"backtrader",
"pybacktest",
"fastquant",
"lean",
"ta",
"finmarketpy",
"qstrader"
            ],
"server": [
"fastapi",
"flask",
"uvicorn",
"gunicorn"
            ],
"framework": [
"lightgbm",
"catboost",
"django"
            ]
        }
        installed = {}
        for category, packages in package_groups.items():
            installed[category] = []
            for pkg in packages:
                try:
                    version = importlib.metadata.version(pkg)
                    installed[category].append({"name": pkg,"version": version})
                except:
                    pass
        return installed

    def setup_vnstock_environment(self):
        env_file = self.id_dir /"environment.json"
        env_data = {
"accepted_agreement": True,
"timestamp": datetime.now().isoformat(),
"machine_id": self.fingerprint()
        }
        try:
            with open(env_file,"w") as f:
                import json
                json.dump(env_data, f)
            return True
        except Exception as e:
            print(f"Failed to set up vnstock environment: {e}")
            return False

    def detect_colab_with_delayed_auth(self, immediate=False):
        is_colab ='google.colab' in sys.modules
        if is_colab and not self._colab_auth_triggered:
            if immediate:
                self._colab_auth_triggered = True
                user_id = self.get_or_create_user_id()
                if user_id and user_id != self.machine_id:
                    self.machine_id = user_id
                    try:
                        with open(self.machine_id_path,"w") as f:
                            f.write(user_id)
                    except:
                        pass
            else:

                def delayed_auth():
                    time.sleep(300)
                    user_id = self.get_or_create_user_id()
                    if user_id and user_id != self.machine_id:
                        self.machine_id = user_id
                        try:
                            with open(self.machine_id_path,"w") as f:
                                f.write(user_id)
                        except:
                            pass
                thread = threading.Thread(target=delayed_auth, daemon=True)
                thread.start()
        return is_colab

    def get_or_create_user_id(self):
        if self._colab_auth_triggered:
            return self.machine_id
        try:
            from google.colab import drive
            print("\n📋 Kết nối tài khoản Google Drive để lưu các thiết lập của dự án.")
            print("Dữ liệu phiên làm việc với Colab của bạn sẽ bị xóa nếu không lưu trữ vào Google Drive.\n")
            self._colab_auth_triggered = True
            drive.mount('/content/drive')
            id_path ='/content/drive/MyDrive/.vnstock/user_id.txt'
            if os.path.exists(id_path):
                with open(id_path,'r') as f:
                    return f.read().strip()
            else:
                user_id = str(uuid.uuid4())
                os.makedirs(os.path.dirname(id_path), exist_ok=True)
                with open(id_path,'w') as f:
                    f.write(user_id)
                return user_id
        except Exception as e:
            return self.machine_id

    def analyze_vibe_coding_maturity(self):
        current_dir = os.getcwd()
        detected_files = []
        l2_markers = ['.cursorrules','.windsurfrules','.clinerules']
        l2_paths = ['.github/copilot-instructions.md']
        l3_markers = ['.agents','.agent','.cline','workflows']
        l4_paths = ['mcp.json','.cursor/mcp.json','.vscode/mcp.json']
        try:
            if os.path.isdir(current_dir):
                root_items = os.listdir(current_dir)
                for item in root_items:
                    if item in l2_markers or item in l3_markers or item =='mcp.json':
                        detected_files.append(item)
                for sub_path in l2_paths + l4_paths:
                    if'/' in sub_path and os.path.exists(os.path.join(current_dir, sub_path)):
                        detected_files.append(sub_path)
            maturity_level = 0
            maturity_title ="Traditional"
            if any(m in detected_files for m in l4_paths + ['mcp.json']):
                maturity_level = 4
                maturity_title ="Ecosystem Integrator"
            elif any(m in detected_files for m in l3_markers):
                maturity_level = 3
                maturity_title ="Agent Orchestrator"
            elif any(m in detected_files for m in l2_markers + l2_paths):
                maturity_level = 2
                maturity_title ="Context Crafter"
            return {
"maturity_level": maturity_level,
"maturity_title": maturity_title,
"detected_markers": list(set(detected_files))
            }
        except Exception:
            return {
"maturity_level": 0,
"maturity_title":"Traditional",
"detected_markers": []
            }

    def analyze_project_structure(self):
        current_dir = os.getcwd()
        project_indicators = {
"commercial_app": ["app","services","products","customers","billing"],
"financial_tool": ["portfolio","backtesting","trading","strategy"],
"data_science": ["models","notebooks","datasets","visualization"],
"educational": ["examples","lectures","assignments","slides"]
        }
        project_type = {}
        for category, markers in project_indicators.items():
            match_count = 0
            for marker in markers:
                if os.path.exists(os.path.join(current_dir, marker)):
                    match_count += 1
            if len(markers) > 0:
                project_type[category] = match_count / len(markers)
        try:
            root_files = [f for f in os.listdir(current_dir) if os.path.isfile(os.path.join(current_dir, f))]
            root_dirs = [d for d in os.listdir(current_dir) if os.path.isdir(os.path.join(current_dir, d))]
            file_markers = {
"python_project": ["setup.py","pyproject.toml","requirements.txt"],
"data_science": ["notebook.ipynb",".ipynb_checkpoints"],
"web_app": ["app.py","wsgi.py","manage.py","server.py"],
"finance_app": ["portfolio.py","trading.py","backtest.py"],
            }
            file_project_type ="unknown"
            for ptype, markers in file_markers.items():
                if any(marker in root_files for marker in markers):
                    file_project_type = ptype
                    break
            frameworks = []
            framework_markers = {
"django": ["manage.py","settings.py"],
"flask": ["app.py","wsgi.py"],
"streamlit": ["streamlit_app.py","app.py"],
"fastapi": ["main.py","app.py"],
            }
            for framework, markers in framework_markers.items():
                if any(marker in root_files for marker in markers):
                    frameworks.append(framework)
        except Exception as e:
            root_files = []
            root_dirs = []
            file_project_type ="unknown"
            frameworks = []
        return {
"project_dir": current_dir,
"detected_type": max(project_type.items(), key=lambda x: x[1])[0] if project_type else"unknown",
"file_type": file_project_type,
"is_git_repo":".git" in (root_dirs if'root_dirs' in locals() else []),
"frameworks": frameworks,
"file_count": len(root_files) if'root_files' in locals() else 0,
"directory_count": len(root_dirs) if'root_dirs' in locals() else 0,
"type_confidence": project_type
        }

    def analyze_git_info(self):
        try:
            result = subprocess.run(["git","rev-parse","--is-inside-work-tree"],
                                capture_output=True, text=True)
            if result.returncode != 0:
                return {"has_git": False}
            repo_root = subprocess.run(["git","rev-parse","--show-toplevel"],
                                    capture_output=True, text=True)
            repo_path = repo_root.stdout.strip() if repo_root.stdout else None
            repo_name = os.path.basename(repo_path) if repo_path else None
            has_license = False
            license_type ="unknown"
            if repo_path:
                license_files = [
                    os.path.join(repo_path,"LICENSE"),
                    os.path.join(repo_path,"LICENSE.txt"),
                    os.path.join(repo_path,"LICENSE.md")
                ]
                for license_file in license_files:
                    if os.path.exists(license_file):
                        has_license = True
                        try:
                            with open(license_file,'r') as f:
                                content = f.read().lower()
                                if"mit license" in content:
                                    license_type ="MIT"
                                elif"apache license" in content:
                                    license_type ="Apache"
                                elif"gnu general public" in content:
                                    license_type ="GPL"
                                elif"bsd " in content:
                                    license_type ="BSD"
                        except:
                            pass
                        break
            remote = subprocess.run(["git","config","--get","remote.origin.url"],
                                capture_output=True, text=True)
            remote_url = remote.stdout.strip() if remote.stdout else None
            if remote_url:
                remote_url = remote_url.strip()
                domain = None
                if remote_url:
                    if remote_url.startswith('git@') or'@' in remote_url and':' in remote_url.split('@')[1]:
                        domain = remote_url.split('@')[1].split(':')[0]
                    elif remote_url.startswith('http'):
                        url_parts = remote_url.split('//')
                        if len(url_parts) > 1:
                            auth_and_domain = url_parts[1].split('/', 1)[0]
                            if'@' in auth_and_domain:
                                domain = auth_and_domain.split('@')[-1]
                            else:
                                domain = auth_and_domain
                    else:
                        import re
                        domain_match = re.search(r'@([^:/]+)|https?://(?:[^@/]+@)?([^/]+)', remote_url)
                        if domain_match:
                            domain = domain_match.group(1) or domain_match.group(2)
                owner = None
                repo_name = None
                if domain:
                    if"github" in domain:
                        if':' in remote_url and'@' in remote_url:
                            parts = remote_url.split(':')[-1].split('/')
                            if len(parts) >= 2:
                                owner = parts[0]
                                repo_name = parts[1].replace('.git','')
                        else:
                            url_parts = remote_url.split('//')
                            if len(url_parts) > 1:
                                path_parts = url_parts[1].split('/')
                                if len(path_parts) >= 3:
                                    domain_part = path_parts[0]
                                    if'@' in domain_part:
                                        owner_index = 1
                                    else:
                                        owner_index = 1
                                    if len(path_parts) > owner_index:
                                        owner = path_parts[owner_index]
                                    if len(path_parts) > owner_index + 1:
                                        repo_name = path_parts[owner_index + 1].replace('.git','')
                commit_count = subprocess.run(["git","rev-list","--count","HEAD"],
                                        capture_output=True, text=True)
                branch_count = subprocess.run(["git","branch","--list"],
                                        capture_output=True, text=True)
                branch_count = len(branch_count.stdout.strip().split('\n')) if branch_count.stdout else 0
                return {
"domain": domain,
"owner": owner,
"commit_count": int(commit_count.stdout.strip()) if commit_count.stdout else 0,
"branch_count": branch_count,
"has_git": True,
"repo_path": repo_path if'repo_path' in locals() else None,
"repo_name": repo_name,
"has_license": has_license if'has_license' in locals() else False,
"license_type": license_type if'license_type' in locals() else"unknown"
                }
        except Exception as e:
            pass
        return {"has_git": False}

    def detect_usage_pattern(self):
        current_time = datetime.now()
        is_weekday = current_time.weekday() < 5
        hour = current_time.hour
        is_business_hours = 9 <= hour <= 18
        return {
"business_hours_usage": is_weekday and is_business_hours,
"weekday": is_weekday,
"hour": hour,
"timestamp": current_time.isoformat()
        }

    def enhanced_commercial_detection(self):
        basic = self.detect_commercial_usage()
        try:
            project_files = os.listdir(os.getcwd())
            commercial_frameworks = ["django-oscar","opencart","magento",
"saleor","odoo","shopify","woocommerce"]
            framework_match = False
            for framework in commercial_frameworks:
                if any(framework in f for f in project_files):
                    framework_match = True
                    break
            db_files = [f for f in project_files if"database" in f.lower()
                      or"db_config" in f.lower() or f.endswith(".db")]
            has_database = len(db_files) > 0
        except:
            framework_match = False
            has_database = False
        domain_check = self.analyze_git_info()
        domain_is_commercial = False
        if domain_check and domain_check.get("domain"):
            commercial_tlds = [".com",".io",".co",".org",".net"]
            domain_is_commercial = any(tld in domain_check["domain"] for tld in commercial_tlds)
        project_structure = self.analyze_project_structure()
        indicators = [
            basic["commercial_probability"],
            framework_match,
            has_database,
            domain_is_commercial,
            project_structure.get("type_confidence", {}).get("commercial_app", 0),
            self.detect_usage_pattern()["business_hours_usage"]
        ]
        indicators = [i for i in indicators if i is not None]
        if indicators:
            score = sum(1.0 if isinstance(i, bool) and i else (i if isinstance(i, (int, float)) else 0)
                      for i in indicators) / len(indicators)
        else:
            score = 0
        return {
"commercial_probability": score,
"likely_commercial": score > 0.4,
"indicators": {
"basic_indicators": basic["commercial_indicators"],
"framework_match": framework_match,
"has_database": has_database,
"domain_is_commercial": domain_is_commercial,
"project_structure": project_structure.get("detected_type"),
"business_hours_usage": self.detect_usage_pattern()["business_hours_usage"]
            }
        }

    def analyze_dependencies(self):
        try:
            try:
                from importlib.metadata import distributions
            except ImportError:
                from importlib_metadata import distributions
            enterprise_packages = [
"snowflake-connector-python","databricks","azure",
"aws","google-cloud","stripe","atlassian",
"salesforce","bigquery","tableau","sap"
            ]
            commercial_deps = []
            for dist in distributions():
                pkg_name = dist.metadata['Name'].lower()
                if any(ent in pkg_name for ent in enterprise_packages):
                    commercial_deps.append({"name": pkg_name,"version": dist.version})
            return {
"has_commercial_deps": len(commercial_deps) > 0,
"commercial_deps_count": len(commercial_deps),
"commercial_deps": commercial_deps
            }
        except:
            return {"has_commercial_deps": False}
inspector = Inspector()