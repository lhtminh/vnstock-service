import os
import pathlib
import json
import time
import threading
import functools
from datetime import datetime
from typing import Optional
import pandas as pd
TC_VAR ="ACCEPT_TC"
TC_VAL ="tôi đồng ý"
TC_PATH = pathlib.Path.home() /".vnstock" /"id" /"terms_agreement.txt"
TERMS_AND_CONDITIONS ="""
Khi tiếp tục sử dụng Vnstock, bạn xác nhận rằng bạn đã đọc, hiểu và đồng ý với Chính sách quyền riêng tư và Điều khoản, điều kiện về giấy phép sử dụng Vnstock.
Chi tiết:
- Giấy phép sử dụng phần mềm: https://vnstocks.com/onboard/giay-phep-su-dung
- Chính sách quyền riêng tư: https://vnstocks.com/onboard/chinh-sach-quyen-rieng-tu
"""

class Core:
    def __init__(self):
        self.initialized = False
        self.webhook_url = None
        self.init_time = datetime.now().isoformat()
        self.home_dir = pathlib.Path.home()
        self.project_dir = self.home_dir /".vnstock"
        self.id_dir = self.project_dir /'id'
        self.terms_file_path = TC_PATH
        self.system_info = None
        self.project_dir.mkdir(exist_ok=True)
        self.id_dir.mkdir(exist_ok=True)
        self.initialize()

    def initialize(self):
        if self.initialized:
            return True
        if not self._check_terms():
            self._accept_terms()
        from vnai.scope.profile import inspector
        inspector.setup_vnstock_environment()
        try:
            from vnai.scope.device import device_registry
            vnstock_version = getattr(__import__('vnstock'),
'__version__','0.0.1')
            if device_registry.needs_reregistration(vnstock_version):
                system_info = inspector.examine()
                device_registry.register(system_info, vnstock_version)
                self.system_info = system_info
            else:
                self.system_info = device_registry.get_registry()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            msg =f"Device registration failed: {e}. Using fallback."
            logger.warning(msg)
            self.system_info = inspector.examine()
        try:
            from vnai.scope.promo import ContentManager
            manager = ContentManager()
            manager.show_startup_ad()
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"Startup ad failed: {e}")
        from vnai.scope.state import record
        record("initialization", {"timestamp": datetime.now().isoformat()})
        from vnai.flow.relay import conduit
        conduit.queue({
"type":"system_info",
"data": {
"commercial": inspector.detect_commercial_usage(),
"packages": inspector.scan_packages()
            }
        }, priority="high")
        self.initialized = True
        _trigger_patching_after_init()
        return True

    def _check_terms(self):
        return os.path.exists(self.terms_file_path)

    def _accept_terms(self):
        from vnai.scope.profile import inspector
        system_info = inspector.examine()
        if TC_VAR in os.environ and os.environ[TC_VAR] == TC_VAL:
            os.environ[TC_VAR] = TC_VAL
        else:
            os.environ[TC_VAR] = TC_VAL
        now = datetime.now()
        machine_id = system_info['machine_id']
        signed_agreement = (
f"Người dùng có mã nhận dạng {machine_id} "
f"đã chấp nhận điều khoản & điều kiện sử dụng Vnstock "
f"lúc {now.isoformat()}\n\n"
f"{TERMS_AND_CONDITIONS}"
        )
        with open(self.terms_file_path,"w", encoding="utf-8") as f:
            f.write(signed_agreement)
        env_file = self.id_dir /"environment.json"
        env_data = {
"accepted_agreement": True,
"timestamp": now.isoformat(),
"machine_id": machine_id
        }
        with open(env_file,"w") as f:
            json.dump(env_data, f)
        return True

    def status(self):
        from vnai.beam.pulse import monitor
        from vnai.scope.state import tracker
        return {
"initialized": self.initialized,
"health": monitor.report(),
"metrics": tracker.get_metrics()
        }

    def configure_privacy(self, level="standard"):
        from vnai.scope.state import tracker
        return tracker.setup_privacy(level)
_core_instance = None
_core_lock = threading.Lock()

def _get_core():
    global _core_instance
    if _core_instance is None:
        with _core_lock:
            if _core_instance is None:
                _core_instance = Core()
    return _core_instance

def tc_init():
    return _get_core().initialize()

def setup():
    return _get_core().initialize()

def optimize_execution(resource_type="default"):
    def decorator(func):
        _optimized_func = [None]
        @functools.wraps(func)

        def wrapper(*args, **kwargs):
            if _optimized_func[0] is None:
                try:
                    setup()
                except Exception:
                    pass
                from vnai.beam.quota import optimize
                actual_decorator = optimize(resource_type)
                _optimized_func[0] = actual_decorator(func)
            return _optimized_func[0](*args, **kwargs)
        return wrapper
    return decorator

def agg_execution(resource_type="default"):
    def decorator(func):
        _optimized_func = [None]
        @functools.wraps(func)

        def wrapper(*args, **kwargs):
            if _optimized_func[0] is None:
                try:
                    setup()
                except Exception:
                    pass
                from vnai.beam.quota import optimize
                actual_decorator = optimize(resource_type, ad_cooldown=1500,
                                          content_trigger_threshold=100000)
                _optimized_func[0] = actual_decorator(func)
            return _optimized_func[0](*args, **kwargs)
        return wrapper
    return decorator

def measure_performance(module_type="function"):
    def decorator(func):
        _captured_func = [None]
        @functools.wraps(func)

        def wrapper(*args, **kwargs):
            if _captured_func[0] is None:
                try:
                    setup()
                except Exception:
                    pass
                from vnai.beam.metrics import capture
                actual_decorator = capture(module_type)
                _captured_func[0] = actual_decorator(func)
            return _captured_func[0](*args, **kwargs)
        return wrapper
    return decorator

def accept_license_terms(terms_text=None):
    if terms_text is None:
        terms_text = TERMS_AND_CONDITIONS
    from vnai.scope.profile import inspector
    system_info = inspector.examine()
    terms_file_path = (
        pathlib.Path.home() /".vnstock" /"id" /
"terms_agreement.txt"
    )
    os.makedirs(os.path.dirname(terms_file_path), exist_ok=True)
    now = datetime.now()
    machine_id = system_info['machine_id']
    with open(terms_file_path,"w", encoding="utf-8") as f:
        f.write(f"Người dùng có mã nhận dạng {machine_id} "
f"đã chấp nhận lúc {now.isoformat()}\n\n")
        f.write(terms_text)
    return True

def accept_vnstock_terms():
    from vnai.scope.profile import inspector
    system_info = inspector.examine()
    home_dir = pathlib.Path.home()
    project_dir = home_dir /".vnstock"
    project_dir.mkdir(exist_ok=True)
    id_dir = project_dir /'id'
    id_dir.mkdir(exist_ok=True)
    env_file = id_dir /"environment.json"
    env_data = {
"accepted_agreement": True,
"timestamp": datetime.now().isoformat(),
"machine_id": system_info['machine_id']
    }
    try:
        with open(env_file,"w") as f:
            json.dump(env_data, f)
        terms_file = id_dir /"terms_agreement.txt"
        now = datetime.now()
        machine_id = system_info['machine_id']
        with open(terms_file,"w", encoding="utf-8") as f:
            f.write(f"Người dùng có mã nhận dạng {machine_id} "
f"đã chấp nhận lúc {now.isoformat()}\n\n")
            f.write(TERMS_AND_CONDITIONS)
        print("Vnstock terms accepted successfully.")
        return True
    except Exception as e:
        print(f"Error accepting terms: {e}")
        return False

def configure_privacy(level="standard"):
    from vnai.scope.state import tracker
    return tracker.setup_privacy(level)

def check_commercial_usage():
    from vnai.scope.profile import inspector
    return inspector.detect_commercial_usage()

def authenticate_for_persistence():
    from vnai.scope.profile import inspector
    return inspector.get_or_create_user_id()

def get_user_tier():
    try:
        from vnai.beam.auth import authenticator
        return authenticator.get_tier_info()
    except Exception as e:
        return {
"tier":"guest",
"description":"Khách (không có API key)",
"limits": {"per_minute": 20,"per_hour": 1200},
"error": str(e)
        }

def refresh_tier_cache():
    try:
        from vnai.beam.auth import authenticator
        authenticator.get_tier(force_refresh=True)
        return True
    except Exception:
        return False

def setup_api_key(api_key):
    from vnai.beam.auth import authenticator
    return authenticator.setup_api_key(api_key)

def get_api_key():
    from vnai.beam.auth import authenticator
    return authenticator.get_api_key()

def remove_api_key():
    from vnai.beam.auth import authenticator
    return authenticator.remove_api_key()

def check_api_key_status():
    from vnai.beam.auth import authenticator
    return authenticator.check_api_key_status()

def print_api_key_help():
    from vnai.beam.auth import authenticator
    return authenticator.print_help()

def get_quota_status(api_key):
    from vnai.beam.quota_endpoint import quota_endpoint
    return quota_endpoint.get_quota_status(api_key)

def get_tier_info():
    from vnai.beam.quota_endpoint import quota_endpoint
    return quota_endpoint.get_tier_info()

def check_quota_available(api_key):
    from vnai.beam.quota_endpoint import quota_endpoint
    return quota_endpoint.check_quota(api_key)

def get_quota_metadata(api_key):
    from vnai.beam.quota_endpoint import quota_endpoint
    return quota_endpoint.get_metadata(api_key)

def record_api_usage(api_key, amount=1):
    from vnai.beam.quota_endpoint import quota_endpoint
    return quota_endpoint.record_usage(api_key, amount)

def balance_sheet(symbol: str, source: str ='vci', period: str ='year',
                 lang: Optional[str] ='en', show_log: bool = False) -> pd.DataFrame:
    _ensure_patches_applied()
    from vnai.beam.fundamental import balance_sheet as get_balance_sheet
    return get_balance_sheet(symbol, source=source, period=period, lang=lang, show_log=show_log)

def income_statement(symbol: str, source: str ='vci', period: str ='year',
                    lang: Optional[str] ='en', show_log: bool = False) -> pd.DataFrame:
    _ensure_patches_applied()
    from vnai.beam.fundamental import income_statement as get_income_statement
    return get_income_statement(symbol, source=source, period=period, lang=lang, show_log=show_log)

def cash_flow(symbol, source='vci', period='year', lang='en', show_log=False):
    _ensure_patches_applied()
    from vnai.beam.fundamental import cash_flow as get_cash_flow
    return get_cash_flow(symbol, source=source, period=period, lang=lang, show_log=show_log)
_patches_initialized = False

def _ensure_patches_applied():
    global _patches_initialized
    if not _patches_initialized:
        try:
            from vnai.beam.patching import apply_all_patches
            apply_all_patches()
            _patches_initialized = True
        except Exception:
            _patches_initialized = True

def _trigger_patching_after_init():
    _ensure_patches_applied()