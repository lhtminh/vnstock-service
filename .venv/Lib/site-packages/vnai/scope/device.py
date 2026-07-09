"""
Device registration and management with IDE detection.
Handles one-time device registration on first install or version update.
Subsequent operations use cached device_id to avoid expensive system scans.
Includes IDE environment detection for comprehensive device profiling.
"""
import json
import os
import psutil
from pathlib import Path
from datetime import datetime
import logging
from typing import Optional, Tuple, Dict, List, Any
logger = logging.getLogger(__name__)

class IDEDetector:
    IDE_MARKERS = {
'pycharm':'PyCharm',
'idea':'IntelliJ IDEA',
'webstorm':'WebStorm',
'code':'VS Code',
'code helper':'VS Code',
'code-server':'VS Code Server',
'code-oss':'VS Code OSS',
'vscodium':'VSCodium',
'cursor':'Cursor',
'cursor helper':'Cursor',
'windsurf':'Windsurf',
'windsurf helper':'Windsurf',
'jupyter-lab':'Jupyter Lab',
'jupyter-notebook':'Classic Jupyter',
'jupyter-server':'Jupyter Server',
'ipython':'IPython',
'docker-init':'Docker Container',
'node':'Node.js',
'antigravity':'Google Antigravity',
'claude':'Claude Code',
'openclaw':'OpenClaw Environment',
'claude-dispatch':'Claude Dispatcher',
    }
    ENV_MARKERS = {
'COLAB_GPU':'Google Colab',
'COLAB_RELEASE_TAG':'Google Colab',
'KAGGLE_KERNEL_RUN_TYPE':'Kaggle Notebook',
'JUPYTERHUB_SERVICE_PREFIX':'JupyterHub',
'OPENCLAW_AGENT':'OpenClaw Agent',
'CLAUDE_DISPATCH':'Claude Dispatcher',
    }
    SHELL_MARKERS = {
'zsh','bash','fish','sh','ksh','tcsh',
'cmd','powershell','pwsh','commandline'
    }
    @staticmethod

    def get_process_chain(max_depth: int = 20) -> List[Dict]:
        try:
            proc = psutil.Process(os.getpid())
            chain = []
            chain.append({
'pid': proc.pid,
'name': proc.name(),
'exe': proc.exe(),
'depth': 0
            })
            for depth, ancestor in enumerate(proc.parents(), start=1):
                if depth > max_depth:
                    break
                try:
                    chain.append({
'pid': ancestor.pid,
'name': ancestor.name(),
'exe': ancestor.exe(),
'depth': depth
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    chain.append({
'pid': ancestor.pid,
'name':'<access_denied or terminated>',
'exe': None,
'depth': depth
                    })
            return chain
        except Exception as e:
            logger.debug(f"Error getting process chain: {e}")
            return []
    @staticmethod

    def _check_jupyter_environment() -> Optional[str]:
        try:
            from IPython import get_ipython
            ipython = get_ipython()
            if ipython is None:
                return None
            kernel_type = type(ipython).__name__
            if'ZMQInteractiveShell' in kernel_type:
                return'Jupyter Kernel'
            elif'TerminalInteractiveShell' in kernel_type:
                return'IPython Terminal'
            else:
                return'IPython'
        except (ImportError, AttributeError):
            return None
    @staticmethod

    def detect_ide() -> Tuple[str, Dict]:
        for env_var, ide_name in IDEDetector.ENV_MARKERS.items():
            if env_var in os.environ:
                return ide_name, {
'detection_method':'environment_variable',
'env_var': env_var,
'detected_at': datetime.now().isoformat(),
                }
        jupyter_env = IDEDetector._check_jupyter_environment()
        if jupyter_env and jupyter_env =='Jupyter Kernel':
            chain = IDEDetector.get_process_chain()
            for process_info in chain:
                name = (process_info['name'] or"").lower()
                for marker, ide_name in IDEDetector.IDE_MARKERS.items():
                    if marker in name and marker not in ['docker-init','node']:
                        ide_display =f"{ide_name} (Jupyter)"
                        return ide_display, {
'detection_method':'jupyter_with_ide_frontend',
'frontend': ide_name,
'detected_at': datetime.now().isoformat(),
                        }
            kernel_name ='Jupyter Kernel'
            return kernel_name, {
'detection_method':'ipython_kernel',
'detected_at': datetime.now().isoformat(),
            }
        chain = IDEDetector.get_process_chain()
        if not chain:
            return'Unknown', {
'detection_method':'failed_to_get_chain',
'detected_at': datetime.now().isoformat(),
            }
        for process_info in chain:
            name = (process_info['name'] or"").lower()
            exe = (process_info['exe'] or"").lower()
            for marker, ide_name in IDEDetector.IDE_MARKERS.items():
                if marker in name or marker in exe:
                    if marker in ['node','docker-init']:
                        chain_names = [p['name'].lower() for p in chain]
                        if not any('jupyter' in n for n in chain_names):
                            continue
                    return ide_name, {
'detection_method':'process_chain',
'matched_process': process_info['name'],
'depth': process_info['depth'],
'detected_at': datetime.now().isoformat(),
                    }
        if chain:
            first_process_name = chain[0]['name'].lower()
            if any(sh in first_process_name for sh in IDEDetector.SHELL_MARKERS):
                return'Terminal', {
'detection_method':'shell_detected',
'shell_name': chain[0]['name'],
'detected_at': datetime.now().isoformat(),
                }
        return'Unknown', {
'detection_method':'no_match',
'detected_at': datetime.now().isoformat(),
        }
    @staticmethod

    def get_ide_info() -> Dict:
        ide_name, detection_info = IDEDetector.detect_ide()
        return {
'ide_name': ide_name,
'detection_method': detection_info.get('detection_method'),
'detected_at': detection_info.get('detected_at'),
'process_chain_depth': detection_info.get('depth'),
'matched_process': detection_info.get('matched_process'),
'environment_variable': detection_info.get('env_var'),
'frontend': detection_info.get('frontend'),
'shell_name': detection_info.get('shell_name'),
        }

def detect_current_ide() -> Tuple[str, Dict]:
    return IDEDetector.detect_ide()

def get_current_ide_info() -> Dict:
    return IDEDetector.get_ide_info()

class DeviceRegistry:
    _instance = None
    _lock = None

    def __new__(cls, project_dir: str | None = None):
        import threading
        if cls._lock is None:
            cls._lock = threading.Lock()
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DeviceRegistry, cls).__new__(cls)
                cls._instance._initialize(project_dir)
            return cls._instance

    def _initialize(self, project_dir: str | None = None) -> None:
        if project_dir is None:
            project_dir = Path.home() /".vnstock"
        else:
            project_dir = Path(project_dir)
        self.id_dir = project_dir /'id'
        self.registry_file = self.id_dir /'hw_info.json'
        old_registry_file = self.id_dir /'device_registry.json'
        if old_registry_file.exists() and not self.registry_file.exists():
            try:
                old_registry_file.rename(self.registry_file)
                logger.info("Migrated device_registry.json → hw_info.json")
            except Exception as e:
                logger.warning(f"Failed to migrate registry file: {e}")
        self.id_dir.mkdir(exist_ok=True, parents=True)
        self._registry = None
        if self.registry_file.exists():
            try:
                with open(self.registry_file,'r', encoding='utf-8') as f:
                    self._registry = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load device registry: {e}")
                self._registry = None

    def is_registered(self, version: str) -> bool:
        if self._registry is None:
            return False
        try:
            installed_version = self._registry.get('version_installed')
            return installed_version == version
        except Exception:
            return False

    def register(
        self,
        device_info: dict,
        version: str,
        ide_info: dict = None
    ) -> dict:
        if ide_info is None:
            try:
                ide_info = get_current_ide_info()
            except Exception:
                ide_info = {}
        registry = {
"device_id": device_info.get('machine_id'),
"register_date": datetime.now().isoformat(),
"version_installed": version,
"os": device_info.get('os_name'),
"os_platform": device_info.get('platform'),
"python": device_info.get('python_version'),
"arch": (
                device_info.get('platform','').split('-')[-1]
                if device_info.get('platform') else'unknown'
            ),
"cpu_count": device_info.get('cpu_count'),
"memory_gb": device_info.get('memory_gb'),
"environment": device_info.get('environment'),
"hosting_service": device_info.get('hosting_service'),
"ide": ide_info,
"reference_data": {
"commercial_usage": device_info.get(
'commercial_usage'
                ),
"packages_snapshot": (
                    device_info.get('dependencies', {}).get(
'vnstock_family', []
                    )
                ),
"git_info": device_info.get('git_info')
            }
        }
        try:
            with open(self.registry_file,'w', encoding='utf-8') as f:
                json.dump(registry, f, indent=2)
            self._registry = registry
            logger.info(
f"Device registered: {device_info.get('machine_id')} "
f"(version {version})"
            )
        except Exception as e:
            logger.error(f"Failed to register device: {e}")
            raise
        return registry

    def get_device_id(self) -> str | None:
        if self._registry is None:
            return None
        try:
            return self._registry.get('device_id')
        except Exception:
            return None

    def get_registry(self) -> dict | None:
        return self._registry

    def get_register_date(self) -> str | None:
        if self._registry is None:
            return None
        try:
            return self._registry.get('register_date')
        except Exception:
            return None

    def needs_reregistration(self, current_version: str) -> bool:
        if self._registry is None:
            return True
        try:
            installed_version = self._registry.get('version_installed')
            return installed_version != current_version
        except Exception:
            return True

    def update_version(self, new_version: str) -> None:
        if self._registry is not None:
            self._registry['version_installed'] = new_version
            self._registry['last_version_update'] = datetime.now().isoformat()
            try:
                with open(self.registry_file,'w', encoding='utf-8') as f:
                    json.dump(self._registry, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to update version in registry: {e}")
device_registry = DeviceRegistry()