import threading
import time
from datetime import datetime

class Monitor:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Monitor, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.health_status ="healthy"
        self.last_check = time.time()
        self.check_interval = 300
        self.error_count = 0
        self.warning_count = 0
        self.status_history = []
        self._start_background_check()

    def _start_background_check(self):
        def check_health():
            while True:
                try:
                    self.check_health()
                except:
                    pass
                time.sleep(self.check_interval)
        thread = threading.Thread(target=check_health, daemon=True)
        thread.start()

    def check_health(self):
        from vnai.beam.metrics import collector
        from vnai.beam.quota import guardian
        self.last_check = time.time()
        metrics_summary = collector.get_metrics_summary()
        has_errors = metrics_summary.get("error", 0) > 0
        resource_usage = guardian.usage()
        high_usage = resource_usage > 80
        if has_errors and high_usage:
            self.health_status ="critical"
            self.error_count += 1
        elif has_errors or high_usage:
            self.health_status ="warning"
            self.warning_count += 1
        else:
            self.health_status ="healthy"
        self.status_history.append({
"timestamp": datetime.now().isoformat(),
"status": self.health_status,
"metrics": metrics_summary,
"resource_usage": resource_usage
        })
        if len(self.status_history) > 10:
            self.status_history = self.status_history[-10:]
        return self.health_status

    def report(self):
        if time.time() - self.last_check > self.check_interval:
            self.check_health()
        return {
"status": self.health_status,
"last_check": datetime.fromtimestamp(self.last_check).isoformat(),
"error_count": self.error_count,
"warning_count": self.warning_count,
"history": self.status_history[-3:],
        }

    def reset(self):
        self.health_status ="healthy"
        self.error_count = 0
        self.warning_count = 0
        self.status_history = []
        self.last_check = time.time()
monitor = Monitor()