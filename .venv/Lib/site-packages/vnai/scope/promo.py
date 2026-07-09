import logging
import requests
import json
from datetime import datetime, timedelta
import random
import threading
import time
import urllib.parse
from pathlib import Path
_vnii_check_attempted = False

class AdCategory:
    FREE = 0
    MANDATORY = 1
    ANNOUNCEMENT = 2
    REFERRAL = 3
    FEATURE = 4
    GUIDE = 5
    SURVEY = 6
    PROMOTION = 7
    SECURITY = 8
    MAINTENANCE = 9
    WARNING = 10
API_KEY_CHECKER_AVAILABLE = None
api_key_checker = None
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

class ContentManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ContentManager, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self, debug=False):
        self.content_base_url ="https://hq.vnstocks.com/content-delivery"
        self.is_paid_user = None
        self.license_checked = False
        self._debug = debug
        global API_KEY_CHECKER_AVAILABLE, api_key_checker
        if API_KEY_CHECKER_AVAILABLE is None:
            try:
                from vnai.scope.lc_integration import api_key_checker as _checker
                api_key_checker = _checker
                API_KEY_CHECKER_AVAILABLE = True
            except ImportError:
                API_KEY_CHECKER_AVAILABLE = False
                api_key_checker = None
        self.last_display = 0
        self.display_interval = 24 * 3600
        self.content_base_url ="https://hq.vnstocks.com/content-delivery"
        self.target_url ="https://vnstocks.com/lp-khoa-hoc-python-chung-khoan"
        self.image_url = (
"https://vnstocks.com/img/trang-chu-vnstock-python-api-phan-tich-giao-dich-chung-khoan.jpg"
        )
        self.vnstock_dir = Path.home() /".vnstock"
        self.message_cache_file = self.vnstock_dir /"message_cache.json"
        self.message_cache = {}
        self._load_message_cache()
        self._start_periodic_display()

    def _load_message_cache(self) -> None:
        try:
            if self.message_cache_file.exists():
                with open(self.message_cache_file,'r') as f:
                    self.message_cache = json.load(f)
            else:
                self.message_cache = {}
        except Exception as e:
            logger.debug(f"Failed to load message cache: {e}")
            self.message_cache = {}

    def _save_message_cache(self) -> None:
        try:
            self.vnstock_dir.mkdir(exist_ok=True)
            with open(self.message_cache_file,'w') as f:
                json.dump(self.message_cache, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save message cache: {e}")

    def should_show_promotional_for_rate_limit(self, tier: str) -> bool:
        if tier !="free":
            return False
        last_promo = self.message_cache.get("last_promotional_message")
        if last_promo:
            try:
                last_time = datetime.fromisoformat(last_promo)
                now = datetime.now()
                if (now - last_time).total_seconds() < 86400:
                    return False
            except Exception as e:
                logger.debug(f"Error parsing last promotional time: {e}")
        session_start = self.message_cache.get("session_start")
        if session_start:
            try:
                start_time = datetime.fromisoformat(session_start)
                now = datetime.now()
                if (now - start_time).total_seconds() < 300:
                    return False
            except Exception as e:
                logger.debug(f"Error parsing session start time: {e}")
        else:
            self.message_cache["session_start"] = datetime.now().isoformat()
            self._save_message_cache()
            return False
        return True

    def mark_promotional_shown(self) -> None:
        self.message_cache["last_promotional_message"] = datetime.now().isoformat()
        self._save_message_cache()

    def _check_license_status(self):
        if self.license_checked:
            return
        if API_KEY_CHECKER_AVAILABLE and api_key_checker:
            try:
                result = api_key_checker.check_license_with_vnii()
                if self._debug:
                    logger.info(f"API key check result: {result}")
                valid_statuses = [
'verified',
'cached',
'device_limit_exceeded'
                ]
                if result.get('status') in valid_statuses:
                    self.is_paid_user = result.get('is_paid', False)
                    self.license_checked = True
                    if self._debug:
                        status_msg = (
"Detected paid user"
                            if self.is_paid_user
                            else"Detected free user"
                        )
                        logger.info(f"{status_msg} via API key")
                else:
                    self.is_paid_user = False
                    self.license_checked = True
                    if self._debug:
                        logger.info(
f"No valid license: {result.get('status')}"
                        )
            except Exception as e:
                if self._debug:
                    logger.error(f"Error checking license via API key: {e}")
                self.is_paid_user = False
                self.license_checked = True
        else:
            if self._debug:
                logger.warning(
"API key checker not available. "
"Cannot determine paid user status."
                )
            self.is_paid_user = False
            self.license_checked = True

    def _has_active_subscription(self) -> bool:
        try:
            from vnai.beam.auth import authenticator
            return authenticator.has_active_subscription()
        except Exception as e:
            if self._debug:
                logger.error(f"Error checking subscription: {e}")
            return False

    def _get_startup_ad_content(self, tier: str) -> dict:
        content = {"html":"","markdown":"","terminal":"","simple":""}
        if tier =='guest':
            content["html"] ="""
            <div style="border: 2px solid #e67e22; padding: 15px; border-radius: 8px; margin: 10px 0; background: linear-gradient(135deg, #fef9e7, #fdebd0);">
                <h3 style="color: #e67e22; margin-top: 0;">🔑 Đăng ký API Key miễn phí để mở khoá tính năng!</h3>
                <p>Bạn đang sử dụng <strong>phiên bản khách</strong> với giới hạn:</p>
                <ul>
                    <li>20 requests/phút | Tối đa 4 kỳ báo cáo tài chính</li>
                </ul>
                <p><strong>Đăng ký API Key miễn phí</strong> để nâng lên 60 requests/phút và 8 kỳ báo cáo:</p>
                <ol>
                    <li>Truy cập <a href="https://vnstocks.com/login" style="color: #2980b9;">vnstocks.com/login</a> để đăng ký</li>
                    <li>Lấy API key tại <a href="https://vnstocks.com/account" style="color: #2980b9;">vnstocks.com/account</a></li>
                    <li>Chạy: <code>vnai.setup_api_key("your_api_key")</code></li>
                </ol>
                <p style="margin-bottom: 5px;">📚 Tài liệu: <a href="https://vnstocks.com/docs" style="color: #2980b9;">vnstocks.com/docs</a> |
                Cộng đồng: <a href="https://facebook.com/groups/vnstock.official" style="color: #2980b9;">Facebook Group</a></p>
                <p style="margin-bottom: 0; color: #e67e22;"><strong>⭐ Tham gia gói tài trợ để sử dụng không giới hạn:</strong>
                <a href="https://vnstocks.com/insiders-program" style="color: #e67e22;">vnstocks.com/insiders-program</a></p>
            </div>
            """
            content["markdown"] ="""
## 🔑 Đăng ký API Key miễn phí để mở khoá tính năng!
Bạn đang sử dụng **phiên bản khách** (20 requests/phút | Tối đa 4 kỳ BCTC).
**Đăng ký API Key miễn phí** để nâng lên 60 requests/phút và 8 kỳ báo cáo:
1. Truy cập [vnstocks.com/login](https://vnstocks.com/login) để đăng ký
2. Lấy API key tại [vnstocks.com/account](https://vnstocks.com/account)
3. Chạy: `vnai.setup_api_key("your_api_key")`
📚 Tài liệu: [vnstocks.com/docs](https://vnstocks.com/docs) | Cộng đồng: [Facebook Group](https://facebook.com/groups/vnstock.official)
⭐ **Tham gia gói tài trợ để sử dụng không giới hạn:** [vnstocks.com/insiders-program](https://vnstocks.com/insiders-program)
            """
            content["terminal"] ="""
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║  🔑 ĐĂNG KÝ API KEY MIỄN PHÍ ĐỂ MỞ KHOÁ TÍNH NĂNG!       ║
║                                                            ║
║  Phiên bản khách: 20 req/phút | Tối đa 4 kỳ BCTC          ║
║                                                            ║
║  Nâng cấp miễn phí (60 req/phút | 8 kỳ BCTC):             ║
║    1. Đăng ký: https://vnstocks.com/login                  ║
║    2. Lấy key: https://vnstocks.com/account                ║
║    3. Chạy: vnai.setup_api_key("your_api_key")             ║
║                                                            ║
║  📚 Tài liệu: https://vnstocks.com/docs                    ║
║  👥 Cộng đồng: https://facebook.com/groups/vnstock.official║
║                                                            ║
║  ⭐ Gói tài trợ (không giới hạn):                           ║
║     https://vnstocks.com/insiders-program                  ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
            """
            content["simple"] = (
"🔑 Đăng ký API Key miễn phí: vnstocks.com/login → vnai.setup_api_key('key') "
"| 📚 Tài liệu: vnstocks.com/docs "
"| ⭐ Gói tài trợ: vnstocks.com/insiders-program"
            )
        elif tier =='free':
            content["html"] ="""
            <div style="border: 2px solid #3498db; padding: 15px; border-radius: 8px; margin: 10px 0; background: linear-gradient(135deg, #ebf5fb, #d6eaf8);">
                <h3 style="color: #3498db; margin-top: 0;">👋 Chào mừng bạn đến với Vnstock!</h3>
                <p>Bạn đang sử dụng <strong>Phiên bản cộng đồng</strong>:</p>
                <ul>
                    <li>60 requests/phút | Tối đa 8 kỳ báo cáo tài chính</li>
                </ul>
                <p style="color: #e67e22;"><strong>⭐ Nâng cấp lên gói tài trợ để:</strong></p>
                <ul>
                    <li>✓ Tăng tốc độ API lên <strong>10X</strong> (180-600 requests/phút)</li>
                    <li>✓ Truy cập <strong>không giới hạn</strong> báo cáo tài chính</li>
                    <li>✓ Sử dụng công cụ kết nối API riêng <strong>vnstock_data</strong> với nhiều tính năng hơn</li>
                </ul>
                <p style="margin-bottom: 0;">➤ <a href="https://vnstocks.com/insiders-program" style="color: #e67e22; font-weight: bold;">Tham gia ngay: vnstocks.com/insiders-program</a></p>
                <p style="margin-top: 5px; font-size: 0.9em;">📚 <a href="https://vnstocks.com/docs" style="color: #3498db;">Tài liệu</a> |
                👥 <a href="https://facebook.com/groups/vnstock.official" style="color: #3498db;">Cộng đồng</a></p>
            </div>
            """
            content["markdown"] ="""
## 👋 Chào mừng bạn đến với Vnstock!
Bạn đang sử dụng **Phiên bản cộng đồng** (60 requests/phút | Tối đa 8 kỳ BCTC).
⭐ **Nâng cấp lên gói tài trợ để:**
* ✓ Tăng tốc độ API lên **10X** (180-600 requests/phút)
* ✓ Truy cập **không giới hạn** báo cáo tài chính
* ✓ Sử dụng công cụ kết nối API riêng **vnstock_data** với nhiều tính năng hơn
➤ **Tham gia ngay:** [vnstocks.com/insiders-program](https://vnstocks.com/insiders-program)
📚 [Tài liệu](https://vnstocks.com/docs) | 👥 [Cộng đồng](https://facebook.com/groups/vnstock.official)
            """
            content["terminal"] ="""
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║  👋 Chào mừng bạn đến với Vnstock!                         ║
║                                                            ║
║  Phiên bản cộng đồng: 60 req/phút | Tối đa 8 kỳ BCTC     ║
║                                                            ║
║  ⭐ NÂNG CẤP LÊN GÓI TÀI TRỢ ĐỂ:                         ║
║    ✓ Tăng tốc độ API lên 10X (180-600 req/phút)           ║
║    ✓ Truy cập không giới hạn báo cáo tài chính            ║
║    ✓ Sử dụng công cụ kết nối API vnstock_data              ║
║                                                            ║
║  ➤ Tham gia: https://vnstocks.com/insiders-program        ║
║                                                            ║
║  📚 Tài liệu: https://vnstocks.com/docs                    ║
║  👥 Cộng đồng: https://facebook.com/groups/vnstock.official║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
            """
            content["simple"] = (
"👋 Chào mừng bạn đến với Vnstock! "
"Phiên bản cộng đồng (60 req/phút). "
"⭐ Nâng cấp gói tài trợ (10X tốc độ): vnstocks.com/insiders-program"
            )
        return content

    def show_startup_ad(self) -> bool:
        if self._has_active_subscription():
            if self._debug:
                logger.info("Skipping startup ad: user is a sponsor member")
            return False
        try:
            from vnai.beam.auth import authenticator
            tier = authenticator.get_tier()
        except Exception:
            tier ='guest'
        if self._debug:
            logger.info(f"Showing startup ad for tier: {tier}")
        environment ='unknown'
        try:
            from vnai.scope.profile import inspector
            environment = inspector.examine().get("environment","unknown")
        except Exception as e:
            logger.debug(f"Environment detection failed: {e}")
        remote_content = self.fetch_remote_content(
            context="init", html=(environment =="jupyter")
        )
        fallback = self._get_startup_ad_content(tier)
        if environment =="jupyter":
            try:
                from IPython.display import display, HTML, Markdown
                if remote_content:
                    display(HTML(remote_content))
                else:
                    try:
                        display(Markdown(fallback["markdown"]))
                    except Exception:
                        display(HTML(fallback["html"]))
            except Exception:
                pass
        elif environment =="terminal":
            if remote_content:
                print(remote_content)
            else:
                print(fallback["terminal"])
        else:
            if remote_content:
                print(remote_content)
            else:
                print(fallback["simple"])
        self.last_display = time.time()
        return True

    def _start_periodic_display(self):
        def periodic_display():
            while True:
                if self._has_active_subscription():
                    break
                sleep_time = random.randint(2 * 3600, 6 * 3600)
                time.sleep(sleep_time)
                if self._has_active_subscription():
                    break
                current_time = time.time()
                if current_time - self.last_display >= self.display_interval:
                    self.present_content(context="periodic")
                else:
                    pass
        thread = threading.Thread(target=periodic_display, daemon=True)
        thread.start()

    def fetch_remote_content(self, context: str ="init", html: bool = True) -> str:
        if not self.license_checked:
            self._check_license_status()
        if self.is_paid_user:
            return""
        try:
            params = {"context": context,"html":"true" if html else"false"}
            url =f"{self.content_base_url}?{urllib.parse.urlencode(params)}"
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                return response.text
            logger.error(f"Non-200 response fetching content: {response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch remote content: {e}")
            return None

    def present_content(self, context: str ="init", ad_category: int = AdCategory.FREE) -> None:
        if not self.license_checked:
            self._check_license_status()
        if self.is_paid_user and ad_category == AdCategory.FREE:
            return
        self.last_display = time.time()
        environment = None
        try:
            from vnai.scope.profile import inspector
            environment = inspector.examine().get("environment","unknown")
        except Exception as e:
            logger.error(f"Không detect được environment: {e}")
            environment ="unknown"
        remote_content = self.fetch_remote_content(
            context=context, html=(environment =="jupyter")
        )
        fallback = self._generate_fallback_content(context)
        if environment =="jupyter":
            try:
                from IPython.display import display, HTML, Markdown
                if remote_content:
                    display(HTML(remote_content))
                else:
                    try:
                        display(Markdown(fallback["markdown"]))
                    except Exception as e:
                        display(HTML(fallback["html"]))
            except Exception as e:
                pass
        elif environment =="terminal":
            if remote_content:
                print(remote_content)
            else:
                print(fallback["terminal"])
        else:
            print(fallback["simple"])

    def _generate_fallback_content(self, context):
        fallback = {"html":"","markdown":"","terminal":"","simple":""}
        if context =="loop":
            fallback["html"] = (
f"""
            <div style="border: 1px solid #e74c3c; padding: 15px; border-radius: 5px; margin: 10px 0;">
                <h3 style="color: #e74c3c;">⚠️ Bạn đang sử dụng vòng lặp với quá nhiều requests</h3>
                <p>Để tránh bị giới hạn tốc độ và tối ưu hiệu suất:</p>
                <ul>
                    <li>Thêm thời gian chờ giữa các lần gọi API</li>
                    <li>Sử dụng xử lý theo batch thay vì lặp liên tục</li>
                    <li>Tham gia gói tài trợ <a href="https://vnstocks.com/insiders-program" style="color: #3498db;">Vnstock Insider</a> để tăng 5X giới hạn API</li>
                </ul>
            </div>
            """
            )
            fallback["markdown"] = (
"""
## ⚠️ Bạn đang sử dụng vòng lặp với quá nhiều requests
Để tránh bị giới hạn tốc độ và tối ưu hiệu suất:
* Thêm thời gian chờ giữa các lần gọi API
* Sử dụng xử lý theo batch thay vì lặp liên tục
* Tham gia gói tài trợ [Vnstock Insider](https://vnstocks.com/insiders-program) để tăng 5X giới hạn API
            """
            )
            fallback["terminal"] = get_promotional_message("terminal")
            fallback["simple"] = get_promotional_message("simple")
        else:
            from vnai.beam.auth import authenticator
            tier = authenticator.get_tier()
            period_limit_info =""
            if tier =='guest':
                period_limit_info = (
"<p style='color: #e67e22; margin-top: 10px;'>"
"<strong>📊 Phiên bản cộng đồng:</strong> Báo cáo tài chính được giới hạn tối đa <strong>4 kỳ</strong> để minh hoạ thuật toán. "
"Để truy cập đầy đủ, vui lòng <a href='https://vnstocks.com/insiders-program' style='color: #e67e22;'>tham gia gói thành viên tài trợ dự án</a>."
"</p>"
                )
            elif tier =='free':
                period_limit_info = (
"<p style='color: #e67e22; margin-top: 10px;'>"
"<strong>📊 Phiên bản cộng đồng:</strong> Báo cáo tài chính được giới hạn tối đa <strong>8 kỳ</strong> để minh hoạ thuật toán. "
"Để truy cập đầy đủ, vui lòng <a href='https://vnstocks.com/insiders-program' style='color: #e67e22;'>tham gia gói thành viên tài trợ dự án</a>."
"</p>"
                )
            fallback["html"] = (
f"""
            <div style="border: 1px solid #3498db; padding: 15px; border-radius: 5px; margin: 10px 0;">
                <h3 style="color: #3498db;">👋 Chào mừng bạn đến với Vnstock!</h3>
                <p>Cảm ơn bạn đã sử dụng công cụ kết nối API dữ liệu chứng khoán cho Python</p>
                <ul>
                    <li>Tài liệu: <a href="https://vnstocks.com/docs/category/s%E1%BB%95-tay-h%C6%B0%E1%BB%9Bng-d%E1%BA%ABn" style="color: #3498db;">vnstocks.com/docs</a></li>
                    <li>Cộng đồng: <a href="https://www.facebook.com/groups/vnstock.official" style="color: #3498db;">vnstocks.com/community</a></li>
                </ul>
                <p>Khám phá các tính năng mới nhất và tham gia cộng đồng để nhận hỗ trợ.</p>
                {period_limit_info}
            </div>
            """
            )
            period_limit_markdown =""
            if tier =='guest':
                period_limit_markdown ="\n**📊 Phiên bản cộng đồng:** Báo cáo tài chính được giới hạn tối đa **4 kỳ** để minh hoạ thuật toán. Để truy cập đầy đủ, vui lòng [tham gia gói thành viên tài trợ dự án](https://vnstocks.com/insiders-program)."
            elif tier =='free':
                period_limit_markdown ="\n**📊 Phiên bản cộng đồng:** Báo cáo tài chính được giới hạn tối đa **8 kỳ** để minh hoạ thuật toán. Để truy cập đầy đủ, vui lòng [tham gia gói thành viên tài trợ dự án](https://vnstocks.com/insiders-program)."
            fallback["markdown"] = (
f"""
## 👋 Chào mừng bạn đến với Vnstock!
Cảm ơn bạn đã sử dụng package phân tích chứng khoán #1 tại Việt Nam
* Tài liệu: [Sổ tay hướng dẫn](https://vnstocks.com/docs)
* Cộng đồng: [Nhóm Facebook](https://facebook.com/groups/vnstock.official)
Khám phá các tính năng mới nhất và tham gia cộng đồng để nhận hỗ trợ.{period_limit_markdown}
                """
            )
            period_limit_terminal =""
            if tier =='guest':
                period_limit_terminal ="\n║  📊 Báo cáo tài chính: Giới hạn 4 kỳ (phiên bản cộng đồng)                ║\n║  Nâng cấp: https://vnstocks.com/insiders-program                ║"
            elif tier =='free':
                period_limit_terminal ="\n║  📊 Báo cáo tài chính: Giới hạn 8 kỳ (phiên bản cộng đồng)                ║\n║  Nâng cấp: https://vnstocks.com/insiders-program                ║"
            fallback["terminal"] = (
f"""
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║  👋 Chào mừng bạn đến với Vnstock!                         ║
║                                                            ║
║  Cảm ơn bạn đã sử dụng package phân tích                   ║
║  chứng khoán #1 tại Việt Nam                               ║
║                                                            ║
║  ✓ Tài liệu: https://vnstocks.com/docs                     ║
║  ✓ Cộng đồng: https://facebook.com/groups/vnstock.official ║{period_limit_terminal}
║                                                            ║
║  Khám phá các tính năng mới nhất và tham gia               ║
║  cộng đồng để nhận hỗ trợ.                                 ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
                """
            )
            period_limit_simple =""
            if tier =='guest':
                period_limit_simple =" | 📊 Báo cáo tài chính: Giới hạn 4 kỳ"
            elif tier =='free':
                period_limit_simple =" | 📊 Báo cáo tài chính: Giới hạn 8 kỳ"
            fallback["simple"] = (
"👋 Chào mừng bạn đến với Vnstock! "
"Tài liệu: https://vnstocks.com/onboard | "
"Cộng đồng: https://facebook.com/groups/vnstock.official"
f"{period_limit_simple}"
            )
        return fallback
manager = ContentManager()

def present(context: str ="init", ad_category: int = AdCategory.FREE) -> None:
    manager.present_content(context=context, ad_category=ad_category)

def get_promotional_message(format_type: str ="terminal") -> str:
    if format_type =="terminal":
        return"""
╔═════════════════════════════════════════════════════════════════╗
║                                                                 ║
║   🚫 ĐANG BỊ CHẶN BỞI GIỚI HẠN API? GIẢI PHÁP Ở ĐÂY!            ║
║                                                                 ║
║   ✓ Tăng ngay 10X tốc độ gọi API - Không còn lỗi RateLimit      ║
║   ✓ Tiết kiệm 85% thời gian chờ đợi giữa các request            ║
║                                                                 ║
║   ➤ NÂNG CẤP NGAY VỚI GÓI TÀI TRỢ VNSTOCK:                      ║
║     https://vnstocks.com/insiders-program                       ║
║                                                                 ║
╚═════════════════════════════════════════════════════════════════╝
"""
    elif format_type =="simple":
        return (
"🚫 Đang bị giới hạn API? Tăng tốc độ gọi API lên 10X với gói "
"Vnstock Insider: https://vnstocks.com/insiders-program"
        )
    elif format_type =="html":
        return"""
<div style="border: 2px solid #e74c3c; padding: 15px; border-radius: 5px; margin: 10px 0; background-color: #fadbd8;">
    <h3 style="color: #c0392b; margin-top: 0;">🚫 ĐANG BỊ CHẶN BỞI GIỚI HẠN API?</h3>
    <p><strong>✓ Tăng ngay 10X tốc độ gọi API - Không còn lỗi RateLimit</strong></p>
    <p><strong>✓ Tiết kiệm 85% thời gian chờ đợi giữa các request</strong></p>
    <p style="margin-bottom: 0;">
        <a href="https://vnstocks.com/insiders-program" style="color: #c0392b; font-weight: bold;">
            ➤ NÂNG CẤP NGAY VỚI GÓI TÀI TRỢ VNSTOCK
        </a>
    </p>
</div>
"""
    else:
        return get_promotional_message("terminal")

def should_show_promotional_for_rate_limit(tier: str) -> bool:
    return manager.should_show_promotional_for_rate_limit(tier)

def mark_promotional_shown() -> None:
    manager.mark_promotional_shown()