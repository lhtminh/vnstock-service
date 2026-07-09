import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
logger = logging.getLogger(__name__)

def _get_ide_info() -> Dict:
    try:
        from vnai.scope.device import get_current_ide_info
        return get_current_ide_info()
    except Exception as e:
        logger.debug(f"Failed to get IDE info: {e}")
        return {}

def _sync_profile_to_api(
    device_info: Dict[str, Any],
    ide_info: Dict[str, Any],
    license_info: Dict[str, Any],
    api_key: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    try:
        import requests
    except ImportError:
        logger.debug("requests library not available, skipping API sync")
        return {
'status':'skipped',
'reason':'requests_not_available',
        }
    try:
        profile = {
'timestamp': datetime.now().isoformat(),
'device': {
'device_id': device_info.get('machine_id'),
'os': device_info.get('os_name'),
'os_platform': device_info.get('platform'),
'python_version': device_info.get('python_version'),
'arch': device_info.get('platform','').split('-')[-1] if device_info.get('platform') else'unknown',
'cpu_count': device_info.get('cpu_count'),
'memory_gb': device_info.get('memory_gb'),
'environment': device_info.get('environment'),
'hosting_service': device_info.get('hosting_service'),
            },
'ide': {
'name': ide_info.get('ide_name'),
'detection_method': ide_info.get('detection_method'),
'detected_at': ide_info.get('detected_at'),
'process_chain_depth': ide_info.get('process_chain_depth'),
'frontend': ide_info.get('frontend'),
            },
'license': {
'is_paid': license_info.get('is_paid'),
'status': license_info.get('status'),
'tier': license_info.get('tier'),
            } if license_info else None,
        }
        payload = {
'profile': profile,
'sync_timestamp': datetime.now().isoformat(),
'sync_version':'2.0',
        }
        headers = {
'Content-Type':'application/json',
'User-Agent':'vnstock-analytics/2.0',
        }
        if api_key:
            headers['Authorization'] =f'Bearer {api_key}'
        endpoint ="https://api.vnstocks.com/v1/user/profile/sync"
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            logger.info("Profile successfully synced to vnstocks.com API")
            return {
'status':'success',
'synced_at': datetime.now().isoformat(),
'api_response': response.json(),
            }
        else:
            logger.debug(f"API sync failed: {response.status_code}")
            return {
'status':'failed',
'error': response.text,
'status_code': response.status_code,
            }
    except requests.exceptions.RequestException as e:
        logger.debug(f"API request failed: {e}")
        return {
'status':'failed',
'error': str(e),
        }
    except Exception as e:
        logger.error(f"Error syncing profile to API: {e}")
        return {
'status':'error',
'error': str(e),
        }

class APIKeyChecker:
    _instance = None
    _lock = None

    def __new__(cls):
        import threading
        if cls._lock is None:
            cls._lock = threading.Lock()
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(APIKeyChecker, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self) -> None:
        self.checked = False
        self.last_check_time = None
        self.is_paid = None
        self.license_info = None

    def _get_vnstock_directories(self) -> list[Path]:
        paths = []
        local_path = Path.home() /".vnstock"
        paths.append(local_path)
        colab_drive_path = Path('/content/drive/MyDrive/.vnstock')
        if colab_drive_path.parent.exists():
            paths.append(colab_drive_path)
        try:
            from vnstock.core.config.ggcolab import get_vnstock_directory
            vnstock_dir = get_vnstock_directory()
            if vnstock_dir not in paths:
                paths.append(vnstock_dir)
        except ImportError:
            pass
        return paths

    def _find_api_key_file(self) -> Optional[Path]:
        for vnstock_dir in self._get_vnstock_directories():
            api_key_path = vnstock_dir /"api_key.json"
            if api_key_path.exists():
                logger.debug(f"Found api_key.json at: {api_key_path}")
                return api_key_path
        logger.debug("api_key.json not found in any vnstock directory")
        return None

    def _read_api_key(self, api_key_path: Path) -> Optional[str]:
        try:
            with open(api_key_path,'r', encoding='utf-8') as f:
                data = json.load(f)
                api_key = data.get('api_key')
                if api_key and isinstance(api_key, str):
                    return api_key.strip()
                else:
                    logger.warning(
f"Invalid api_key format in {api_key_path}"
                    )
                    return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {api_key_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading {api_key_path}: {e}")
            return None

    def check_license_with_vnii(
        self,
        force: bool = False,
        include_ide_info: bool = True
    ) -> Dict[str, Any]:
        if self.checked and not force:
            result = {
'is_paid': self.is_paid,
'status':'cached',
'checked_at': self.last_check_time,
'api_key_found': True,
'vnii_available': True
            }
            if include_ide_info:
                result['ide_info'] = _get_ide_info()
            return result
        result = {
'is_paid': False,
'status':'unknown',
'checked_at': datetime.now().isoformat(),
'api_key_found': False,
'vnii_available': False
        }
        if include_ide_info:
            result['ide_info'] = _get_ide_info()
        try:
            from vnii import lc_init
            result['vnii_available'] = True
        except ImportError:
            logger.debug("vnii package not available")
            result['status'] ='vnii_not_installed'
            return result
        api_key_path = self._find_api_key_file()
        if not api_key_path:
            logger.debug("No api_key.json found")
            result['status'] ='no_api_key_file'
            return result
        api_key = self._read_api_key(api_key_path)
        if not api_key:
            logger.warning("Could not read API key from file")
            result['status'] ='invalid_api_key_file'
            return result
        result['api_key_found'] = True
        try:
            from vnii import lc_init
            import os
            original_env = os.environ.get('VNSTOCK_API_KEY')
            os.environ['VNSTOCK_API_KEY'] = api_key
            try:
                license_info = lc_init(debug=False)
                status = license_info.get('status','').lower()
                tier = license_info.get('tier','').lower()
                is_paid = (
'recognized and verified' in status or
                    tier in ['bronze','silver','golden','gold']
                )
                result['is_paid'] = is_paid
                result['status'] ='verified' if is_paid else'free_user'
                result['license_info'] = license_info
                self.checked = True
                self.last_check_time = result['checked_at']
                self.is_paid = is_paid
                self.license_info = license_info
                logger.info(
f"License verified via vnii: "
f"is_paid={is_paid}, tier={tier}"
                )
            finally:
                if original_env is None:
                    os.environ.pop('VNSTOCK_API_KEY', None)
                else:
                    os.environ['VNSTOCK_API_KEY'] = original_env
        except SystemExit as e:
            error_msg = str(e)
            if'device limit exceeded' in error_msg.lower():
                logger.warning(f"Device limit exceeded but user is paid")
                result['status'] ='device_limit_exceeded'
                result['is_paid'] = True
                result['error'] = error_msg
                self.checked = True
                self.last_check_time = result['checked_at']
                self.is_paid = True
                self.license_info = {'status':'Device limit','tier':'paid'}
            else:
                logger.warning(f"vnii license check failed: {e}")
                result['status'] ='license_check_failed'
                result['error'] = error_msg
        except Exception as e:
            logger.error(f"Error calling vnii lc_init: {e}")
            result['status'] ='error'
            result['error'] = str(e)
        return result

    def sync_profile_to_api(
        self,
        device_info: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        try:
            ide_info = _get_ide_info()
            license_info = {
'is_paid': self.is_paid,
'status':'verified' if self.is_paid else'free_user',
'tier': self.license_info.get('tier') if self.license_info else None,
            } if self.checked else None
            if device_info is None:
                try:
                    from vnai.scope.profile import inspector
                    device_data = inspector.examine()
                    device_info = {
'machine_id': device_data.get('machine_id'),
'os_name': device_data.get('os_name'),
'platform': device_data.get('platform'),
'python_version': device_data.get('python_version'),
'cpu_count': device_data.get('cpu_count'),
'memory_gb': device_data.get('memory_gb'),
'environment': device_data.get('environment'),
'hosting_service': device_data.get('hosting_service'),
                    }
                except Exception as e:
                    logger.debug(f"Failed to get device info: {e}")
                    device_info = {}
            return _sync_profile_to_api(
                device_info=device_info,
                ide_info=ide_info,
                license_info=license_info,
                api_key=api_key,
                force=force
            )
        except Exception as e:
            logger.error(f"Error in sync_profile_to_api: {e}")
            return {
'status':'error',
'error': str(e),
            }

    def is_paid_user(self) -> Optional[bool]:
        if not self.checked:
            result = self.check_license_with_vnii()
            return result.get('is_paid')
        return self.is_paid

    def get_license_info(self) -> Optional[Dict]:
        return self.license_info
api_key_checker = APIKeyChecker()

def check_license_via_api_key(force: bool = False) -> Dict[str, Any]:
    return api_key_checker.check_license_with_vnii(force=force)

def is_paid_user_via_api_key() -> Optional[bool]:
    return api_key_checker.is_paid_user()

def check_license_status() -> Optional[bool]:
    try:
        is_paid = api_key_checker.is_paid_user()
        return is_paid
    except ImportError:
        logger.warning("API key checker not available")
        return None
    except Exception as e:
        logger.error(f"Error checking license status: {e}")
        return None

def update_license_from_vnii() -> bool:
    try:
        result = api_key_checker.check_license_with_vnii(force=True)
        if result.get('status') in ['verified','cached']:
            is_paid = result.get('is_paid', False)
            logger.info(f"License updated via API key: is_paid={is_paid}")
            return True
        else:
            logger.warning(
f"Failed to update license: {result.get('status')}"
            )
            return False
    except Exception as e:
        logger.error(f"Error updating license from vnii: {e}")
        return False

def sync_user_profile_to_api(
    api_key: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    return api_key_checker.sync_profile_to_api(api_key=api_key, force=force)