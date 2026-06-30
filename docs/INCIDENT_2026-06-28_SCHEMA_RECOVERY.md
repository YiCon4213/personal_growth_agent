# Incident Report: schemas.py Worktree Deletion and Recovery

Date: 2026-06-28
Status: resolved
Affected file: backend/app/models/schemas.py

## Summary

During Phase 3 development, the normal patch tool could read the repository but could not write files through the Windows sandbox when the workspace path contained non-ASCII characters. A fallback git apply attempt was made against a dirty worktree. Git removed the existing file before the sandbox denied creation of the replacement, leaving schemas.py deleted.

Phase 1 and Phase 2 changes in that file had not been committed or staged, so Git HEAD did not contain the latest version. No secrets, database data, or external systems were affected. The source file was restored from HEAD only after explicit user approval, then the Phase 1/2 schema changes were reconstructed from current code, tests, and API call sites.

## Impact

- backend/app/models/schemas.py was temporarily missing.
- Its uncommitted Phase 1/2 changes could not be recovered directly from Git.
- Phase 3 implementation paused until recovery was authorized and verified.
- Other project files were not deleted by the failed patch.
- The recovery was validated by the complete pre-Phase-3 backend suite: 71 tests passed.

## Trigger and Root Cause

The direct trigger was a fallback git apply operation that passed content matching but failed while writing the target file. On this Windows workspace, the sandbox/path layer behaved inconsistently with the repository's non-ASCII path.

Root causes:

1. The standard patch tool failed on the workspace path.
2. The fallback operation was allowed to touch a file with known uncommitted changes.
3. No verified out-of-repository snapshot of the dirty file existed before the fallback.
4. A patch content check does not guarantee that the later filesystem write will succeed.
5. Phase 2 had not yet been committed, so HEAD was only a baseline, not a complete recovery point.

The absence of a Phase 2 commit increased recovery cost, but it did not cause the filesystem failure. The unsafe fallback decision was the operational error.

## Recovery

1. Stopped further write attempts after the deletion was detected.
2. Searched Git unreachable objects, Python bytecode, and IDE Local History for a lossless copy.
3. Requested explicit authorization before restoring from the older HEAD version.
4. Restored the HEAD baseline.
5. Rebuilt conversation and advanced-RAG schemas from verified current callers and tests.
6. Ran the complete backend suite; all 71 pre-Phase-3 tests passed.
7. Created an external temporary snapshot of all Phase 3 target files before resuming work.
8. Completed Phase 3 and reran the expanded backend and frontend verification.

## Prevention Rules

1. Treat a dirty worktree as user-owned state. Never run a fallback patch, checkout, restore, reset, or bulk rewrite against it without a recoverable snapshot.
2. Before changing a dirty file through an unproven write path, copy the exact file to an out-of-repository temporary backup and verify it.
3. If the standard patch tool fails because of path or sandbox behavior, stop. Do not switch to git apply on the same dirty file merely because the patch content validates.
4. Test any fallback writer on a new disposable file in the same directory before touching an existing file.
5. Strongly recommend a user-approved checkpoint commit after each accepted phase.
6. Never assume Git HEAD contains current work. Check git status --short and distinguish committed, staged, modified, and untracked state.
7. After recovery, use the full relevant test suite as the equivalence gate; import or syntax success alone is insufficient.
8. Never commit secrets, .env, virtual environments, node_modules, .next, or local data.

## Future Recovery Runbook

1. Stop all writes.
2. Record git status --short and the exact failed operation.
3. Search external snapshots, IDE Local History, editor backups, staged blobs, and unreachable Git objects.
4. Do not restore from HEAD until the user is told that HEAD may be older and explicitly approves.
5. Restore to a temporary candidate first when possible.
6. Compare the candidate against current imports, models, migrations, and tests.
7. Run the complete relevant verification baseline.
8. Document remaining uncertainty before resuming feature work.
