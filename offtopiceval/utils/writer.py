import json
from queue import Queue
from threading import Event, Thread




class DeamonWriter:
    def __init__(self, filename, mode="a"):
        self.filename = filename
        self.mode = mode
        self._queue = Queue()  # queue to store datapoints for processing
        self._flag = Event()  # add an event to close the thread upon completion
        self._thread = Thread(target=self.write, daemon=True)
        self._thread.start()  # start the thread right away

    def put(self, obj):
        self._queue.put(obj)

    def _write(self, obj, f):
        try:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            f.flush()
        except Exception as e:
            print(f"\n | > Deamon Writer - Error writing to file: {e}. Skipping ...")

    def write(self):
        with open(self.filename, self.mode, encoding="utf-8") as f:
            while True:
                # this is a busy wait
                # not so efficient, but it works
                obj = self._queue.get()
                self._write(obj, f)
                self._queue.task_done()

    def graceful_terminate(self):
        while not self._queue.empty():
            obj = self._queue.get()
            with open(self.filename, "a", encoding="utf-8") as f:
                self._write(obj, f)
            self._queue.task_done()

        self._flag.set()
        self._queue.join()