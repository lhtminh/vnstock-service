import sys
import time
import threading
from datetime import datetime
import hashlib
import json

class Collector:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Collector, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.metrics = {
"function": [],
"rate_limit": [],
"request": [],
"error": []
        }
        self.thresholds = {
"buffer_size": 50,
"error_threshold": 0.1,
"performance_threshold": 5.0
        }
        self.function_count = 0
        self.colab_auth_triggered = False
        self.max_metric_length = 200
        self._last_record_time = {}
        self.min_interval_per_type = 0.5
        self._recent_hashes = []
        self._sending_metrics = False

    def record(self, metric_type, data, priority=None):
        if not isinstance(data, dict):
            data = {"value": str(data)}
        if"timestamp" not in data:
            data["timestamp"] = datetime.now().isoformat()
        if metric_type !="system_info":
            data.pop("system", None)
            from vnai.scope.profile import inspector
            data["machine_id"] = inspector.fingerprint()
        now = time.time()
        last_time = self._last_record_time.get(metric_type, 0)
        if now - last_time < self.min_interval_per_type and priority !="high":
            return
        self._last_record_time[metric_type] = now
        data_hash = hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()
        if data_hash in self._recent_hashes and priority !="high":
            return
        self._recent_hashes.append(data_hash)
        if metric_type in self.metrics:
            self.metrics[metric_type].append(data)
            if len(self.metrics[metric_type]) > self.max_metric_length:
                self.metrics[metric_type] = self.metrics[metric_type][-self.max_metric_length:]
        else:
            self.metrics["function"].append(data)
        if metric_type =="function":
            self.function_count += 1
            if self.function_count > 10 and not self.colab_auth_triggered and'google.colab' in sys.modules:
                self.colab_auth_triggered = True
                threading.Thread(target=self._trigger_colab_auth, daemon=True).start()
        if sum(len(metric_list) for metric_list in self.metrics.values()) >= self.thresholds["buffer_size"]:
            self._send_metrics()
        if priority =="high" or metric_type =="error":
            self._send_metrics()

    def _trigger_colab_auth(self):
        try:
            from vnai.scope.profile import inspector
            inspector.get_or_create_user_id()
        except:
            pass

    def _send_metrics(self):
        if self._sending_metrics:
            return
        self._sending_metrics = True
        try:
            from vnai.flow.relay import track_function_call, track_rate_limit, track_api_request
        except ImportError:
            for metric_type in self.metrics:
                self.metrics[metric_type] = []
            self._sending_metrics = False
            return
        for metric_type, data_list in self.metrics.items():
            if not data_list:
                continue
            for data in data_list:
                try:
                    if metric_type =="function":
                        track_function_call(
                            function_name=data.get("function","unknown"),
                            source=data.get("source","vnai"),
                            execution_time=data.get("execution_time", 0),
                            success=data.get("success", True),
                            error=data.get("error"),
                            args=data.get("args")
                        )
                    elif metric_type =="rate_limit":
                        track_rate_limit(
                            source=data.get("source","vnai"),
                            limit_type=data.get("limit_type","unknown"),
                            limit_value=data.get("limit_value", 0),
                            current_usage=data.get("current_usage", 0),
                            is_exceeded=data.get("is_exceeded", False)
                        )
                    elif metric_type =="request":
                        track_api_request(
                            endpoint=data.get("endpoint","unknown"),
                            source=data.get("source","vnai"),
                            method=data.get("method","GET"),
                            status_code=data.get("status_code", 200),
                            execution_time=data.get("execution_time", 0),
                            request_size=data.get("request_size", 0),
                            response_size=data.get("response_size", 0)
                        )
                except Exception as e:
                    continue
            self.metrics[metric_type] = []
        self._sending_metrics = False

    def get_metrics_summary(self):
        return {
            metric_type: len(data_list)
            for metric_type, data_list in self.metrics.items()
        }
collector = Collector()

def capture(module_type="function"):
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            success = False
            error = None
            try:
                result = func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                error = str(e)
                collector.record("error", {
"function": func.__name__,
"error": error,
"args": str(args)[:100] if args else None
                })
                raise
            finally:
                execution_time = time.time() - start_time
                collector.record(
                    module_type,
                    {
"function": func.__name__,
"execution_time": execution_time,
"success": success,
"error": error,
"timestamp": datetime.now().isoformat(),
"args": str(args)[:100] if args else None
                    }
                )
        return wrapper
    return decorator