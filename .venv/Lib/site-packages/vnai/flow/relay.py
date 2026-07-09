import time
import threading
import json
import random
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

class Conduit:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, buffer_size=50, sync_interval=300):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Conduit, cls).__new__(cls)
                cls._instance._initialize(buffer_size, sync_interval)
            return cls._instance

    def _initialize(self, buffer_size, sync_interval):
        self.buffer_size = buffer_size
        self.sync_interval = sync_interval
        self.buffer = {
"function_calls": [],
"api_requests": [],
"rate_limits": []
        }
        self.lock = threading.Lock()
        self.last_sync_time = time.time()
        self.sync_count = 0
        self.failed_queue = []
        self.project_dir = self._get_project_dir()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.project_dir /'data'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.data_dir /"relay_config.json"
        try:
            from vnai.scope.profile import inspector
            self.machine_id = inspector.fingerprint()
        except Exception:
            self.machine_id = self._generate_fallback_id()
        self._load_config()
        self._start_periodic_sync()

    def _get_project_dir(self) -> Path:
        try:
            from vnstock.core.config.ggcolab import get_vnstock_directory
            return get_vnstock_directory()
        except ImportError:
            return Path.home() /".vnstock"

    def _generate_fallback_id(self) -> str:
        try:
            import platform
            import hashlib
            import uuid
            system_info = platform.node() + platform.platform() + platform.processor()
            return hashlib.md5(system_info.encode()).hexdigest()
        except:
            import uuid
            return str(uuid.uuid4())

    def _load_config(self):
        if self.config_path.exists():
            try:
                with open(self.config_path,'r') as f:
                    config = json.load(f)
                if'buffer_size' in config:
                    self.buffer_size = config['buffer_size']
                if'sync_interval' in config:
                    self.sync_interval = config['sync_interval']
                if'last_sync_time' in config:
                    self.last_sync_time = config['last_sync_time']
                if'sync_count' in config:
                    self.sync_count = config['sync_count']
            except:
                pass

    def _save_config(self):
        config = {
'buffer_size': self.buffer_size,
'sync_interval': self.sync_interval,
'last_sync_time': self.last_sync_time,
'sync_count': self.sync_count
        }
        try:
            with open(self.config_path,'w') as f:
                json.dump(config, f)
        except:
            pass

    def _start_periodic_sync(self):
        def periodic_sync():
            while True:
                time.sleep(self.sync_interval)
                self.dispatch("periodic")
        sync_thread = threading.Thread(target=periodic_sync, daemon=True)
        sync_thread.start()

    def add_function_call(self, record):
        if not isinstance(record, dict):
            record = {"value": str(record)}
        with self.lock:
            self.buffer["function_calls"].append(record)
            self._check_triggers("function_calls")

    def add_api_request(self, record):
        if not isinstance(record, dict):
            record = {"value": str(record)}
        with self.lock:
            self.buffer["api_requests"].append(record)
            self._check_triggers("api_requests")

    def add_rate_limit(self, record):
        if not isinstance(record, dict):
            record = {"value": str(record)}
        with self.lock:
            self.buffer["rate_limits"].append(record)
            self._check_triggers("rate_limits")

    def _check_triggers(self, record_type: str):
        current_time = time.time()
        should_trigger = False
        trigger_reason = None
        total_records = sum(len(buffer) for buffer in self.buffer.values())
        if total_records >= self.buffer_size:
            should_trigger = True
            trigger_reason ="buffer_full"
        elif record_type =="rate_limits" and self.buffer["rate_limits"] and             any(item.get("is_exceeded") for item in self.buffer["rate_limits"] if isinstance(item, dict)):
            should_trigger = True
            trigger_reason ="rate_limit_exceeded"
        elif record_type =="function_calls" and self.buffer["function_calls"] and             any(not item.get("success") for item in self.buffer["function_calls"] if isinstance(item, dict)):
            should_trigger = True
            trigger_reason ="function_error"
        else:
            time_factor = min(1.0, (current_time - self.last_sync_time) / (self.sync_interval / 2))
            if random.random() < 0.05 * time_factor:
                should_trigger = True
                trigger_reason ="random_time_weighted"
        if should_trigger:
            threading.Thread(
                target=self.dispatch,
                args=(trigger_reason,),
                daemon=True
            ).start()

    def queue(self, package, priority=None):
        try:
            from vnai.scope.promo import ContentManager
            is_paid = ContentManager().is_paid_user
            segment_val ="paid" if is_paid else"free"
        except Exception:
            segment_val ="free"

        def ensure_segment(d):
            if not isinstance(d, dict):
                return d
            d = dict(d)
            if"segment" not in d:
                d["segment"] = segment_val
            return d
        if isinstance(package, dict) and"segment" not in package:
            import base64
            api_key = base64.b64decode("MXlJOEtnYXJudFFyMHB0cmlzZUhoYjRrZG9ta2VueU5JOFZQaXlrNWFvVQ==").decode()
            package["segment"] = segment_val
        if isinstance(package, dict) and isinstance(package.get("data"), dict):
            if"segment" not in package["data"]:
                package["data"]["segment"] = segment_val
        """Queue data package"""
        if not package:
            return False
        if not isinstance(package, dict):
            self.add_function_call(ensure_segment({"message": str(package)}))
            return True
        if"timestamp" not in package:
            package["timestamp"] = datetime.now().isoformat()
        if"type" in package:
            package_type = package["type"]
            data = package.get("data", {})
            if isinstance(data, dict) and"system" in data:
                machine_id = data["system"].get("machine_id")
                data.pop("system")
                if machine_id:
                    data["machine_id"] = machine_id
            if package_type =="function":
                self.add_function_call(ensure_segment(data))
            elif package_type =="api_request":
                self.add_api_request(ensure_segment(data))
            elif package_type =="rate_limit":
                self.add_rate_limit(ensure_segment(data))
            elif package_type =="system_info":
                self.add_function_call({
"type":"system_info",
"commercial": data.get("commercial"),
"packages": data.get("packages"),
"timestamp": package.get("timestamp")
                })
            elif package_type =="metrics":
                metrics_data = data
                for metric_type, metrics_list in metrics_data.items():
                    if isinstance(metrics_list, list):
                        if metric_type =="function":
                            for item in metrics_list:
                                self.add_function_call(ensure_segment(item))
                        elif metric_type =="rate_limit":
                            for item in metrics_list:
                                self.add_rate_limit(ensure_segment(item))
                        elif metric_type =="request":
                            for item in metrics_list:
                                self.add_api_request(ensure_segment(item))
            else:
                if isinstance(data, dict) and data is not package:
                    self.add_function_call(ensure_segment(data))
                else:
                    self.add_function_call(ensure_segment(package))
        else:
            self.add_function_call(ensure_segment(package))
        if priority =="high":
            self.dispatch("high_priority")
        return True

    def _send_data(self, payload):
        import base64
        api_key = base64.b64decode("MXlJOEtnYXJudFFyMHB0cmlzZUhoYjRrZG9ta2VueU5JOFZQaXlrNWFvVQ==").decode()
        url ="https://hq.vnstocks.com/analytics"
        headers = {
"x-api-key": api_key,
"Content-Type":"application/json"
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def dispatch(self, reason="manual"):
        with self.lock:
            if all(len(records) == 0 for records in self.buffer.values()):
                return False
            data_to_send = {
"function_calls": self.buffer["function_calls"].copy(),
"api_requests": self.buffer["api_requests"].copy(),
"rate_limits": self.buffer["rate_limits"].copy()
            }
            self.buffer = {
"function_calls": [],
"api_requests": [],
"rate_limits": []
            }
            self.last_sync_time = time.time()
            self.sync_count += 1
            self._save_config()
        machine_id = self.machine_id
        try:
            from vnai.scope.device import device_registry
            cached_id = device_registry.get_device_id()
            if cached_id:
                machine_id = cached_id
        except Exception:
            pass
        payload = {
"analytics_data": data_to_send,
"metadata": {
"timestamp": datetime.now().isoformat(),
"machine_id": machine_id,
"sync_count": self.sync_count,
"trigger_reason": reason,
"data_counts": {
"function_calls": len(data_to_send["function_calls"]),
"api_requests": len(data_to_send["api_requests"]),
"rate_limits": len(data_to_send["rate_limits"])
                }
            }
        }
        success = self._send_data(payload)
        if not success:
            with self.lock:
                self.failed_queue.append(payload)
                if len(self.failed_queue) > 10:
                    self.failed_queue = self.failed_queue[-10:]
        with self.lock:
            to_retry = self.failed_queue.copy()
            self.failed_queue = []
        success_count = 0
        for payload in to_retry:
            if self._send_data(payload):
                success_count += 1
            else:
                with self.lock:
                    self.failed_queue.append(payload)
        return success_count
conduit = Conduit()

def track_function_call(function_name, source, execution_time, success=True, error=None, args=None):
    record = {
"function": function_name,
"source": source,
"execution_time": execution_time,
"timestamp": datetime.now().isoformat(),
"success": success
    }
    if error:
        record["error"] = error
    if args:
        sanitized_args = {}
        if isinstance(args, dict):
            for key, value in args.items():
                if isinstance(value, (str, int, float, bool)):
                    sanitized_args[key] = value
                else:
                    sanitized_args[key] = str(type(value))
        else:
            sanitized_args = {"value": str(args)}
        record["args"] = sanitized_args
    conduit.add_function_call(record)

def track_rate_limit(source, limit_type, limit_value, current_usage, is_exceeded):
    record = {
"source": source,
"limit_type": limit_type,
"limit_value": limit_value,
"current_usage": current_usage,
"is_exceeded": is_exceeded,
"timestamp": datetime.now().isoformat(),
"usage_percentage": (current_usage / limit_value) * 100 if limit_value > 0 else 0
    }
    conduit.add_rate_limit(record)

def track_api_request(endpoint, source, method, status_code, execution_time, request_size=0, response_size=0):
    record = {
"endpoint": endpoint,
"source": source,
"method": method,
"status_code": status_code,
"execution_time": execution_time,
"timestamp": datetime.now().isoformat(),
"request_size": request_size,
"response_size": response_size
    }
    conduit.add_api_request(record)

def sync_now():
    return conduit.dispatch("manual")

def retry_failed():
    return conduit.retry_failed()