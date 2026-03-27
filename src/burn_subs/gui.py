from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from .core import BurnOptions, ConvertResult, convert_files
from .ffmpeg import probe_streams, resolve_binaries


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
        self._audio_choices: list[tuple[int, str]] = []
        self._subtitle_choices: list[tuple[int, str]] = []

        self._configure_theme()
        self._build_ui()
        self._set_default_stream_dropdowns()
        self._poll_results()

    def _configure_theme(self) -> None:
        """
        Force a readable ttk theme/colors.
        Some Tk/macOS combinations can render white text on white buttons.
        """
        style = ttk.Style(self)
        themes = set(style.theme_names())
        if "clam" in themes:
            style.theme_use("clam")

        style.configure("TButton", padding=6, foreground="black", background="#f0f0f0")
        style.configure("TLabel", foreground="black")
        style.configure("TCheckbutton", foreground="black")
        style.configure("TSpinbox", foreground="black")
        style.map(
            "TButton",
            foreground=[("disabled", "#777777"), ("!disabled", "black")],
            background=[("active", "#e6e6e6"), ("!disabled", "#f0f0f0")],
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        controls = ttk.Frame(outer)
        controls.pack(fill="x")

        ttk.Button(controls, text="Add files…", command=self._add_files).pack(side="left")
        ttk.Button(controls, text="Clear", command=self._clear_files).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Refresh streams", command=self._refresh_streams).pack(side="left", padx=(8, 0))

        ttk.Label(controls, text="Output dir:").pack(side="left", padx=(16, 4))
        self.output_dir_var = tk.StringVar(value="_out")
        ttk.Entry(controls, textvariable=self.output_dir_var, width=28).pack(side="left")
        ttk.Button(controls, text="Browse…", command=self._choose_output_dir).pack(side="left", padx=(6, 0))

        opts = ttk.Frame(outer)
        opts.pack(fill="x", pady=(12, 0))

        ttk.Label(opts, text="Audio index:").pack(side="left")
        self.audio_choice_var = tk.StringVar()
        self.audio_combo = ttk.Combobox(opts, textvariable=self.audio_choice_var, width=24, state="readonly")
        self.audio_combo.pack(side="left", padx=(6, 16))

        ttk.Label(opts, text="Subtitle index:").pack(side="left")
        self.subtitle_choice_var = tk.StringVar()
        self.subtitle_combo = ttk.Combobox(opts, textvariable=self.subtitle_choice_var, width=28, state="readonly")
        self.subtitle_combo.pack(side="left", padx=(6, 16))

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
        if self._files:
            self._load_stream_choices_from_first_file(self._files[0])
        self.progress_var.set(f"Selected files: {len(self._files)}")

    def _clear_files(self) -> None:
        self._files.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._set_default_stream_dropdowns()
        self.progress_var.set("Idle")

    def _choose_output_dir(self) -> None:
        d = filedialog.askdirectory(title="Select output directory")
        if d:
            self.output_dir_var.set(d)

    def _refresh_streams(self) -> None:
        if not self._files:
            messagebox.showinfo("burn-subs", "Add at least one file to detect streams.")
            return
        self._load_stream_choices_from_first_file(self._files[0])
        self.progress_var.set("Refreshed stream choices from first file")

    def _set_default_stream_dropdowns(self) -> None:
        self._audio_choices = [(0, "0 - unknown")]
        self._subtitle_choices = [(0, "0 - unknown")]
        self.audio_combo["values"] = [label for _, label in self._audio_choices]
        self.subtitle_combo["values"] = [label for _, label in self._subtitle_choices]
        self.audio_choice_var.set(self._audio_choices[0][1])
        self.subtitle_choice_var.set(self._subtitle_choices[0][1])

    def _load_stream_choices_from_first_file(self, first_file: str) -> None:
        try:
            bins = resolve_binaries()
            streams = probe_streams(ffprobe_bin=bins.ffprobe, input_file=first_file)
        except Exception:
            streams = []

        audio_choices: list[tuple[int, str]] = []
        subtitle_choices: list[tuple[int, str]] = []

        audio_seq = 0
        sub_seq = 0
        for s in streams:
            lang = s.language if s.language else "unknown"
            title = f" ({s.title})" if s.title else ""
            if s.codec_type == "audio":
                label = f"{audio_seq} - {lang}{title}"
                audio_choices.append((audio_seq, label))
                audio_seq += 1
            elif s.codec_type == "subtitle":
                label = f"{sub_seq} - {lang}{title}"
                subtitle_choices.append((sub_seq, label))
                sub_seq += 1

        if not audio_choices:
            audio_choices = [(0, "0 - unknown")]
        has_subs = bool(subtitle_choices)
        if not subtitle_choices:
            subtitle_choices = [(0, "0 - (no subtitles detected)")]

        self._audio_choices = audio_choices
        self._subtitle_choices = subtitle_choices
        self.audio_combo["values"] = [label for _, label in audio_choices]
        self.subtitle_combo["values"] = [label for _, label in subtitle_choices]
        # Auto-select: Japanese audio + English subs.
        # Fallbacks:
        # - audio: index 0 if JP not present
        # - subs: EN if present else index 0; if no subs exist, enable "No subs".
        self.audio_choice_var.set(self._preferred_label(audio_choices, ("jpn", "ja", "jp")))
        if has_subs:
            self.no_subs_var.set(False)
            self.subtitle_combo.configure(state="readonly")
            self.subtitle_choice_var.set(self._preferred_label(subtitle_choices, ("eng", "en")))
        else:
            self.no_subs_var.set(True)
            self.subtitle_combo.configure(state="disabled")
            self.subtitle_choice_var.set(subtitle_choices[0][1])

    def _preferred_label(self, choices: list[tuple[int, str]], lang_priority: tuple[str, ...]) -> str:
        for lang in lang_priority:
            needle = f" - {lang.lower()}"
            for _, label in choices:
                if needle in label.lower():
                    return label
        return choices[0][1]

    def _selected_audio_index(self) -> int:
        label = self.audio_choice_var.get().strip()
        for idx, lbl in self._audio_choices:
            if lbl == label:
                return idx
        return 0

    def _selected_subtitle_index(self) -> int:
        label = self.subtitle_choice_var.get().strip()
        for idx, lbl in self._subtitle_choices:
            if lbl == label:
                return idx
        return 0

    def _run(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("burn-subs", "A conversion is already running.")
            return
        if not self._files:
            messagebox.showwarning("burn-subs", "Add at least one input file first.")
            return

        options = BurnOptions(
            subtitle_stream_index=None if self.no_subs_var.get() else self._selected_subtitle_index(),
            audio_index=self._selected_audio_index(),
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

