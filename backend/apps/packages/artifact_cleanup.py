"""Helpers for cleaning package build artifacts when package metadata changes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
import logging

from django.conf import settings

from backend.apps.packages.models import PackageBuild

logger = logging.getLogger(__name__)


def wipe_package_artifacts_for_rebuild(package, reason: str = "") -> dict:
    """
    Remove cached sources and built artifacts for a package.

    This is used when metadata changes (version/extras) invalidate previous
    build outputs.
    """
    deleted_files = 0
    deleted_dirs = 0
    removed_repo_files = 0
    touched_repo_dirs = set()

    build_root = Path(settings.REQPM["BUILD_DIR"])
    artifact_basenames = set()

    direct_paths = [package.srpm_path or "", package.rpm_path or ""]
    for p in direct_paths:
        if not p:
            continue
        artifact_basenames.add(Path(p).name)
        try:
            fp = Path(p)
            if fp.exists():
                fp.unlink()
                deleted_files += 1
        except Exception as e:
            logger.warning("Could not delete artifact file %s: %s", p, e)

    builds = list(PackageBuild.objects.filter(package=package))
    for b in builds:
        if b.srpm_path:
            artifact_basenames.add(Path(b.srpm_path).name)
            try:
                fp = Path(b.srpm_path)
                if fp.exists():
                    fp.unlink()
                    deleted_files += 1
            except Exception as e:
                logger.warning("Could not delete build SRPM %s: %s", b.srpm_path, e)

        for rpm in (b.rpm_paths or []):
            if not rpm:
                continue
            artifact_basenames.add(Path(rpm).name)
            try:
                fp = Path(rpm)
                if fp.exists():
                    fp.unlink()
                    deleted_files += 1
            except Exception as e:
                logger.warning("Could not delete build RPM %s: %s", rpm, e)

    source_dir = build_root / "sources" / package.name
    if source_dir.exists():
        try:
            shutil.rmtree(source_dir)
            deleted_dirs += 1
        except Exception as e:
            logger.warning("Could not remove source dir %s: %s", source_dir, e)

    # Clear the DB-backed sources_fetched_at timestamp so source_fetched returns False
    try:
        package.sources_fetched_at = None
        package.save(update_fields=['sources_fetched_at'])
    except Exception as e:
        logger.warning("Could not clear sources_fetched_at for package %s: %s", package.id, e)

    pkg_build_dir = build_root / "package_builds" / str(package.id)
    if pkg_build_dir.exists():
        try:
            shutil.rmtree(pkg_build_dir)
            deleted_dirs += 1
        except Exception as e:
            logger.warning("Could not remove package build dir %s: %s", pkg_build_dir, e)

    project_repo_root = build_root / "projects" / str(package.project_id)
    if project_repo_root.exists() and artifact_basenames:
        for repo_file in project_repo_root.rglob("*"):
            if not repo_file.is_file():
                continue
            if repo_file.name not in artifact_basenames:
                continue
            try:
                repo_file.unlink()
                removed_repo_files += 1
                touched_repo_dirs.add(repo_file.parent)
            except Exception as e:
                logger.warning("Could not remove local-repo artifact %s: %s", repo_file, e)

        for repo_dir in touched_repo_dirs:
            try:
                subprocess.run(
                    ["createrepo_c", "--update", str(repo_dir)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except Exception as e:
                logger.warning("Could not refresh repo metadata for %s: %s", repo_dir, e)

    PackageBuild.objects.filter(package=package).delete()

    cleanup = {
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "removed_repo_files": removed_repo_files,
        "deleted_build_rows": len(builds),
    }
    if reason:
        logger.info("Artifact cleanup for %s (%s): %s", package.name, reason, cleanup)
    return cleanup


def reset_package_build_state(package) -> None:
    """Reset package build-related fields after cleanup."""
    package.build_status = "not_built"
    package.build_started_at = None
    package.build_completed_at = None
    package.build_log = ""
    package.build_root_log = ""
    package.build_error_message = ""
    package.analyzed_errors = []
    package.srpm_path = ""
    package.rpm_path = ""
    package.last_built_at = None
    package.save(
        update_fields=[
            "build_status",
            "build_started_at",
            "build_completed_at",
            "build_log",
            "build_root_log",
            "build_error_message",
            "analyzed_errors",
            "srpm_path",
            "rpm_path",
            "last_built_at",
        ]
    )
