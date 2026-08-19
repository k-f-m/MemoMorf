from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ModelStatusInfo:
    model_key: str
    display_name: str
    state: str
    cache_root: Path
    snapshot_dir: Path | None
    incomplete_files: int

    @property
    def can_delete(self) -> bool:
        return self.cache_root.exists()


class ModelCacheManager:
    def __init__(
        self,
        cache_dir: Path,
        repository_map: dict[str, str],
        required_files: set[str],
        display_names: dict[str, str],
        display_order: tuple[str, ...],
    ) -> None:
        self.cache_dir = cache_dir
        self.repository_map = repository_map
        self.required_files = required_files
        self.display_names = display_names
        self.display_order = display_order

    def get_model_cache_root(self, model_key: str) -> Path:
        repo_name = self.repository_map[model_key].replace("/", "--")
        return self.cache_dir / f"models--{repo_name}"

    def get_incomplete_blob_paths(self, model_key: str) -> list[Path]:
        blobs_dir = self.get_model_cache_root(model_key) / "blobs"
        if not blobs_dir.exists():
            return []
        return sorted(
            blob_path
            for blob_path in blobs_dir.iterdir()
            if blob_path.name.endswith(".incomplete")
        )

    def cleanup_incomplete_model_files(self, model_key: str) -> None:
        for blob_path in self.get_incomplete_blob_paths(model_key):
            blob_path.unlink(missing_ok=True)

    def get_local_model_snapshot(self, model_key: str) -> Path | None:
        cache_root = self.get_model_cache_root(model_key)
        refs_main = cache_root / "refs" / "main"
        if not refs_main.exists():
            return None

        revision = refs_main.read_text(encoding="utf-8").strip()
        if not revision:
            return None

        snapshot_dir = cache_root / "snapshots" / revision
        if not snapshot_dir.exists():
            return None

        if not all((snapshot_dir / required_file).exists() for required_file in self.required_files):
            return None

        return snapshot_dir

    def list_statuses(self) -> list[ModelStatusInfo]:
        statuses: list[ModelStatusInfo] = []
        for model_key in self.display_order:
            cache_root = self.get_model_cache_root(model_key)
            snapshot_dir = self.get_local_model_snapshot(model_key)
            incomplete_files = len(self.get_incomplete_blob_paths(model_key))

            if snapshot_dir is not None:
                state = "Downloaded"
            elif incomplete_files:
                suffix = "file" if incomplete_files == 1 else "files"
                state = f"Incomplete download ({incomplete_files} temp {suffix})"
            elif cache_root.exists():
                state = "Partial cache"
            else:
                state = "Not downloaded"

            statuses.append(
                ModelStatusInfo(
                    model_key=model_key,
                    display_name=self.display_names[model_key],
                    state=state,
                    cache_root=cache_root,
                    snapshot_dir=snapshot_dir,
                    incomplete_files=incomplete_files,
                )
            )
        return statuses

    def delete_model(self, model_key: str) -> bool:
        cache_root = self.get_model_cache_root(model_key)
        if not cache_root.exists():
            return False
        shutil.rmtree(cache_root)
        return True

    def clear_all(self) -> bool:
        if not self.cache_dir.exists():
            return False
        shutil.rmtree(self.cache_dir)
        return True