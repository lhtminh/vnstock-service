import time
import threading
import json
import os
from datetime import datetime
from pathlib import Path

class Tracker:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Tracker, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.metrics = {
"startup_time": datetime.now().isoformat(),
"function_calls": 0,
"api_requests": 0,
"errors": 0,
"warnings": 0
        }
        self.performance_metrics = {
"execution_times": [],
"last_error_time": None,
"peak_memory": 0
        }
        self.privacy_level ="standard"
        self.home_dir = Path.home()
        self.project_dir = self.home_dir /".vnstock"
        self.project_dir.mkdir(exist_ok=True)
        self.data_dir = self.project_dir /'data'
        self.data_dir.mkdir(exist_ok=True)
        self.metrics_path = self.data_dir /"usage_metrics.json"
        self.privacy_config_path = self.project_dir /'config' /"privacy.json"
        os.makedirs(os.path.dirname(self.privacy_config_path), exist_ok=True)
        self._load_metrics()
        self._load_privacy_settings()
        self._start_background_collector()

    def _load_metrics(self):
        if self.metrics_path.exists():
            try:
                with open(self.metrics_path,'r') as f:
                    stored_metrics = json.load(f)
                for key, value in stored_metrics.items():
                    if key in self.metrics:
                        self.metrics[key] = value
            except:
                pass

    def _save_metrics(self):
        try:
            with open(self.metrics_path,'w') as f:
                json.dump(self.metrics, f)
        except:
            pass

    def _load_privacy_settings(self):
        if self.privacy_config_path.exists():
            try:
                with open(self.privacy_config_path,'r') as f:
                    settings = json.load(f)
                    self.privacy_level = settings.get("level","standard")
            except:
                pass

    def setup_privacy(self, level=None):
        privacy_levels = {
"minimal":"Essential system data only",
"standard":"Performance metrics and errors",
"enhanced":"Detailed operation analytics"
        }
        if level is None:
            level ="standard"
        if level not in privacy_levels:
            raise ValueError(f"Invalid privacy level: {level}. Choose from {', '.join(privacy_levels.keys())}")
        self.privacy_level = level
        with open(self.privacy_config_path,"w") as f:
            json.dump({"level": level}, f)
        return level

    def get_privacy_level(self):
        return self.privacy_level

    def _start_background_collector(self):
        def collect_metrics():
            while True:
                try:
                    import psutil
                    current_process = psutil.Process()
                    memory_info = current_process.memory_info()
                    memory_usage = memory_info.rss / (1024 * 1024)
                    if memory_usage > self.performance_metrics["peak_memory"]:
                        self.performance_metrics["peak_memory"] = memory_usage
                    self._save_metrics()
                except:
                    pass
                time.sleep(300)
        thread = threading.Thread(target=collect_metrics, daemon=True)
        thread.start()

    def record(self, event_type, data=None):
        if self.privacy_level =="minimal" and event_type !="errors":
            return True
        if event_type in self.metrics:
            self.metrics[event_type] += 1
        else:
            self.metrics[event_type] = 1
        if event_type =="errors":
            self.performance_metrics["last_error_time"] = datetime.now().isoformat()
        if event_type =="function_calls" and data and"execution_time" in data:
            self.performance_metrics["execution_times"].append(data["execution_time"])
            if len(self.performance_metrics["execution_times"]) > 100:
                self.performance_metrics["execution_times"] = self.performance_metrics["execution_times"][-100:]
        if self.metrics["function_calls"] % 100 == 0 or event_type =="errors":
            self._save_metrics()
        return True

    def get_metrics(self):
        avg_execution_time = 0
        if self.performance_metrics["execution_times"]:
            avg_execution_time = sum(self.performance_metrics["execution_times"]) / len(self.performance_metrics["execution_times"])
        output = self.metrics.copy()
        output.update({
"avg_execution_time": avg_execution_time,
"peak_memory_mb": self.performance_metrics["peak_memory"],
"uptime": (datetime.now() - datetime.fromisoformat(self.metrics["startup_time"])).total_seconds(),
"privacy_level": self.privacy_level
        })
        return output

    def reset(self):
        self.metrics = {
"startup_time": datetime.now().isoformat(),
"function_calls": 0,
"api_requests": 0,
"errors": 0,
"warnings": 0
        }
        self.performance_metrics = {
"execution_times": [],
"last_error_time": None,
"peak_memory": 0
        }
        self._save_metrics()
        return True
tracker = Tracker()

def record(event_type, data=None):
    return tracker.record(event_type, data)