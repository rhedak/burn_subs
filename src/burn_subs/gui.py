from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from .core import BurnOptions, ConvertResult, convert_files


@dataclass(frozen=True)
class _Job:
    files: list[str]
    output_dir: str
    options: BurnOptions


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("burn-subs")
        self.geometry("900x520")

        self._files: list[str] = []
        self._worker: threading.Thread | None = None
        self._result_queue: queue.Queue[ConvertResult | None] = queue.Queue()

        self._build_ui()
        self._poll_results()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        controls = ttk.Frame(outer)
        controls.pack(fill="x")

        ttk.Button(controls, text="Add files…", command=self._add_files).pack(side="left")
        ttk.Button(controls, text="Clear", command=self._clear_files).pack(side="left", padx=(8, 0))

        ttk.Label(controls, text="Output dir:").pack(side="left", padx=(16, 4))
        self.output_dir_var = tk.StringVar(value="_out")
        ttk.Entry(controls, textvariable=self.output_dir_var, width=28).pack(side="left")
        ttk.Button(controls, text="Browse…", command=self._choose_output_dir).pack(side="left", padx=(6, 0))

        opts = ttk.Frame(outer)
        opts.pack(fill="x", pady=(12, 0))

        ttk.Label(opts, text="Audio index:").pack(side="left")
        self.audio_index_var = tk.IntVar(value=0)
        ttk.Spinbox(opts, from_=0, to=99, textvariable=self.audio_index_var, width=6).pack(side="left", padx=(6, 16))

        ttk.Label(opts, text="Subtitle index:").pack(side="left")
        self.subtitle_index_var = tk.IntVar(value=0)
        ttk.Spinbox(opts, from_=0, to=99, textvariable=self.subtitle_index_var, width=6).pack(side="left", padx=(6, 16))

        self.no_subs_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="No subs (no-op)", variable=self.no_subs_var).pack(side="left")

        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Overwrite outputs", variable=self.overwrite_var).pack(side="left", padx=(12, 0))

        action = ttk.Frame(outer)
        action.pack(fill="x", pady=(12, 0))

        self.run_btn = ttk.Button(action, text="Run conversion", command=self._run)
        self.run_btn.pack(side="left")

        self.progress_var = tk.StringVar(value="Idle")
        ttk.Label(action, textvariable=self.progress_var).pack(side="left", padx=(12, 0))

        columns = ("status", "input", "output", "method")
        self.tree = ttk.Treeview(outer, columns=columns, show="headings", height=16)
        self.tree.heading("status", text="Status")
        self.tree.heading("input", text="Input")
        self.tree.heading("output", text="Output")
        self.tree.heading("method", text="Method")
        self.tree.column("status", width=80, anchor="w")
        self.tree.column("input", width=360, anchor="w")
        self.tree.column("output", width=360, anchor="w")
        self.tree.column("method", width=80, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(12, 0))

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select video files",
            filetypes=[
                ("Video files", "*.mkv *.mp4 *.mov *.m4v *.avi *.ts"),
                ("All files", "*.*"),
            ],
        )
        if not paths:
            return
        for p in paths:
            if p not in self._files:
                self._files.append(p)
                self.tree.insert("", "end", values=("PENDING", p, "", ""))
        self.progress_var.set(f"Selected files: {len(self._files)}")

    def _clear_files(self) -> None:
        self._files.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.progress_var.set("Idle")

    def _choose_output_dir(self) -> None:
        d = filedialog.askdirectory(title="Select output directory")
        if d:
            self.output_dir_var.set(d)

    def _run(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("burn-subs", "A conversion is already running.")
            return
        if not self._files:
            messagebox.showwarning("burn-subs", "Add at least one input file first.")
            return

        options = BurnOptions(
            subtitle_stream_index=None if self.no_subs_var.get() else int(self.subtitle_index_var.get()),
            audio_index=int(self.audio_index_var.get()),
            overwrite=bool(self.overwrite_var.get()),
        )
        job = _Job(files=list(self._files), output_dir=self.output_dir_var.get(), options=options)

        self.run_btn.configure(state="disabled")
        self.progress_var.set("Running…")

        # Reset table outputs/methods to blank.
        for i, item in enumerate(self.tree.get_children()):
            vals = list(self.tree.item(item, "values"))
            vals[0] = "RUNNING"
            vals[2] = ""
            vals[3] = ""
            self.tree.item(item, values=tuple(vals))

        self._worker = threading.Thread(target=self._worker_run, args=(job,), daemon=True)
        self._worker.start()

    def _worker_run(self, job: _Job) -> None:
        try:
            results = convert_files(job.files, output_dir=job.output_dir, options=job.options)
            for r in results:
                self._result_queue.put(r)
        finally:
            self._result_queue.put(None)

    def _poll_results(self) -> None:
        done = False
        updated = 0
        while True:
            try:
                item = self._result_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                done = True
                break
            updated += 1
            self._apply_result(item)

        if done:
            self.run_btn.configure(state="normal")
            self.progress_var.set("Done")
            self._show_summary()

        self.after(150, self._poll_results)

    def _apply_result(self, r: ConvertResult) -> None:
        # Update matching row by input path.
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            if vals and vals[1] == r.input_file:
                status = "OK" if r.ok else "FAIL"
                method = r.method or ""
                out = r.output_file or ""
                self.tree.item(item, values=(status, r.input_file, out, method))
                break

    def _show_summary(self) -> None:
        results: list[tuple[str, tuple]] = []
        for item in self.tree.get_children():
            results.append((item, self.tree.item(item, "values")))

        ok = sum(1 for _, v in results if v and v[0] == "OK")
        fail = sum(1 for _, v in results if v and v[0] == "FAIL")
        total = len(results)
        messagebox.showinfo("burn-subs", f"Completed {total} file(s).\nOK: {ok}\nFAIL: {fail}")


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

