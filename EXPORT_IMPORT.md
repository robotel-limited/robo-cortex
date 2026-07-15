# Export/Import: Sharing Knowledge Across Projects

**Quick Start:** Export learnings from one project, import into another. Enables team collaboration and multi-project learning.

---

## Basic Workflow

### Step 1: Export from project with learnings

```bash
cd /path/to/project-with-learnings
robo-cortex export --scope global --output kb.jsonl

# Output:
# ✅ Exported 15 global-scoped memories to kb.jsonl
```

### Step 2: Import into new project

```bash
cd /path/to/new-project
robo-cortex init  # (if not already initialized)
robo-cortex import kb.jsonl

# Output:
# ✅ Import complete:
#    ✓ Imported: 15 memories
```

### Step 3: Use the imported knowledge

```bash
robo-cortex retrieve --task "your task"
# Now returns learnings from imported KB!
```

---

## Command Reference

### `robo-cortex export`

Export memories to portable JSONL format.

```bash
robo-cortex export [--scope SCOPE] [--output FILE]

Options:
  --scope global|repo    Memory scope to export (default: global)
  --output FILE          Output file (default: stdout)

Examples:
  # Export global learnings to file
  robo-cortex export --scope global --output kb.jsonl
  
  # Export to stdout
  robo-cortex export --scope global
  
  # Export repo-scoped memories (project-specific)
  robo-cortex export --scope repo --output repo-kb.jsonl
```

### `robo-cortex import`

Import memories from JSONL file.

```bash
robo-cortex import FILE

Arguments:
  FILE    Input JSONL file to import

Examples:
  # Import knowledge base
  robo-cortex import kb.jsonl
  
  # Import from another location
  robo-cortex import ~/backups/kb_2026-07-13.jsonl
```

---

## JSONL Format

Each line is a complete JSON memory object:

```jsonl
{"id": 1, "type": "lesson", "scope": "global", "statement": "Copy-to-clipboard fallback: Use dual-method. Modern: navigator.clipboard.writeText(). Fallback: textarea + execCommand('copy'). Essential for HTTP contexts.", "confidence": "high", "assumptions": "Web app with copy-to-clipboard feature, needs to work on HTTP and HTTPS", "status": "active", "created_at": "2026-07-13T...", ...}
{"id": 2, "type": "lesson", "scope": "global", "statement": "FastAPI doesn't serve static files by default. Add: app.mount('/static', StaticFiles(directory='static'), name='static').", "confidence": "high", ...}
```

**Format properties:**
- One memory per line
- Valid JSON per line
- Human-readable (can open in text editor)
- Mergeable (can concatenate exports)
- Portable (move between machines, share via git)

---

## Use Cases

### 1. Team Knowledge Base

**Scenario:** Team of developers working on multiple FastAPI projects. Share learnings.

```bash
# Team lead exports team KB
cd project-alpha
robo-cortex export --scope global --output team-kb.jsonl

# Commit and share
git add team-kb.jsonl
git commit -m "Add shared team knowledge base"
git push

# Team members import
git pull
cd ../project-beta
robo-cortex import team-kb.jsonl
# Now they have all of project-alpha's learnings!
```

### 2. Backup and Restore

**Scenario:** Before major refactor or machine migration, backup memories.

```bash
# Backup before machine migration
robo-cortex export --scope global --output ~/backups/kb_$(date +%Y-%m-%d).jsonl

# On new machine, restore
robo-cortex import ~/backups/kb_2026-07-13.jsonl
# All memories restored!
```

### 3. Multi-Project Learning (Knowledge Compounding)

**Scenario:** 5 projects, each learns from prior projects' mistakes.

```
Project 1 (test-cortex):
  $ robo-cortex export --scope global --output kb_v1.jsonl
  → Saves 10 lessons learned

Project 2 (test2-cortex):
  $ robo-cortex init
  $ robo-cortex import ../test-cortex/kb_v1.jsonl
  → Now has 10 lessons + discovers 5 more
  $ robo-cortex export --scope global --output kb_v2.jsonl
  
Project 3 (test3-cortex):
  $ robo-cortex import ../test2-cortex/kb_v2.jsonl
  → Now has 15 lessons + discovers 3 more
  $ robo-cortex export --scope global --output kb_v3.jsonl

Project 4+:
  → Growing library of lessons
  → Each project starts smarter than the last
```

### 4. Onboarding New Team Member

**Scenario:** New developer joins team. Give them all prior projects' learnings.

```bash
# Create team KB from all past projects
cd project-alpha && robo-cortex export --scope global --output kb_alpha.jsonl
cd project-beta  && robo-cortex export --scope global --output kb_beta.jsonl
cd project-gamma && robo-cortex export --scope global --output kb_gamma.jsonl

# Combine exports
cat kb_*.jsonl > team-all-learnings.jsonl

# New dev onboards
cd onboarding-project
robo-cortex init
robo-cortex import team-all-learnings.jsonl
# Now they know what the team has learned from 3 projects!
```

---

## Best Practices

### Naming Convention

```bash
# Include project name + date
robo-cortex export --scope global --output kb_project-alpha_2026-07-13.jsonl

# Or include version
robo-cortex export --scope global --output kb_v1.0.jsonl

# Avoid generic names (better: kb_project-name_date.jsonl)
# ❌ kb.jsonl
# ✅ kb_myapp_2026-07-13.jsonl
```

### Scope Selection

```bash
# Global scope: reusable across projects
robo-cortex export --scope global

# Repo scope: project-specific (e.g., "use async/await for this codebase")
robo-cortex export --scope repo

# Usually export global scope for sharing; keep repo scope local
```

### Versioning

```bash
# Keep versioned exports for history
kb_2026-07-01.jsonl  (v1: 5 lessons)
kb_2026-07-08.jsonl  (v2: 8 lessons)
kb_2026-07-13.jsonl  (v3: 12 lessons)

# Import latest
robo-cortex import kb_2026-07-13.jsonl
```

### Git Workflow

```bash
# Commit team KB to repo
git add team-kb.jsonl
git commit -m "Update team knowledge base (15 lessons)"

# Or keep in separate knowledge-base repo
git clone knowledge-base
cd knowledge-base && robo-cortex init
robo-cortex import team-kb.jsonl
```

---

## Behavior

### Import is Idempotent

```bash
# Import same file twice - no duplicates
robo-cortex import kb.jsonl
# Output: Imported 15 memories

robo-cortex import kb.jsonl
# Output: Skipped 15 (already exist)
```

### Duplicate Handling

If a memory with same ID and scope already exists:
- Import **skips it** (idempotent, safe)
- Reports in output: `ℹ️  Memory ID X (scope) already exists, skipping`
- No warnings or errors

### Conflict Resolution

If you merge two KBs with overlapping IDs:
- Manually edit JSONL to change IDs, OR
- Import sequentially and let duplicates auto-skip

---

## Troubleshooting

### Export returns 0 memories

```bash
# Check: Are you exporting the right scope?
robo-cortex export --scope global  # Exports global.db
robo-cortex export --scope repo    # Exports .cortex/memory.db (local)

# Global memories live in ~/.cortex/global.db
# Repo memories live in .cortex/memory.db
```

### Import fails with "File not found"

```bash
# Verify file path
ls -l /path/to/kb.jsonl

# Use absolute path
robo-cortex import ~/kb.jsonl      # absolute
robo-cortex import ./kb.jsonl      # relative to CWD
```

### Import reports all skipped

```bash
# Memories already imported (idempotent)
# This is normal if you import the same file twice

# If you want fresh import, you can:
# 1. Remove old memories manually (not recommended)
# 2. Rename memory IDs in JSONL before importing
```

---

## Examples

### Complete Team Onboarding

```bash
# Step 1: Project 1 learns, exports
cd project-alpha
robo-cortex export --scope global --output kb_alpha.jsonl
git add kb_alpha.jsonl && git commit "Export team learnings"

# Step 2: Project 2 imports + learns + exports
cd ../project-beta
robo-cortex init
robo-cortex import ../project-alpha/kb_alpha.jsonl
# Now work, discover new patterns...
robo-cortex export --scope global --output kb_beta.jsonl

# Step 3: New project gets all prior learnings
cd ../project-gamma
robo-cortex init
robo-cortex import ../project-alpha/kb_alpha.jsonl
robo-cortex import ../project-beta/kb_beta.jsonl
# Now has all learnings from 2 prior projects!
```

### Backup Before Major Refactor

```bash
# Before refactor
robo-cortex export --scope global --output ~/kb_backup_$(date +%Y-%m-%d).jsonl

# After refactor (if needed to restore)
robo-cortex import ~/kb_backup_2026-07-13.jsonl
```

### Share KB via Git

```bash
# Create public knowledge-base repo
git init knowledge-base && cd knowledge-base
robo-cortex init

# Add team learnings
robo-cortex import team-kb.jsonl
git add -A && git commit "Initial team KB"
git push origin main

# Other teams: clone + import
git clone <knowledge-base-repo>
cd knowledge-base
robo-cortex import team-kb.jsonl
```

---

## Format Spec (JSONL)

Each line must be valid JSON with these fields:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | int | ✓ | Must be unique within scope |
| type | string | ✓ | fact, decision, lesson, hypothesis, convention, experiment, open_question |
| scope | string | ✓ | global or repo |
| statement | string | ✓ | Max 500 chars |
| confidence | string | ✓ | low, medium, high |
| why_it_matters | string | - | Max 300 chars |
| assumptions | string | - | Required if scope=global, max 500 chars |
| status | string | - | active, provisional, needs_review, superseded, invalidated, abandoned, archived |
| status_reason | string | - | Why status was set |
| created_at | string | - | ISO 8601 datetime |
| last_verified_at | string | - | ISO 8601 datetime |
| created_by | string | - | Attribution (e.g., "agent", "alice") |

Example:
```json
{"id": 1, "type": "lesson", "scope": "global", "statement": "...", "confidence": "high", "why_it_matters": "...", "assumptions": "...", "status": "active", "created_at": "2026-07-13T10:36:27Z", "created_by": "agent"}
```

---

## Merging Knowledge Bases

### Bidirectional Sync: `robo-cortex merge`

**Scenario:** Two projects have diverged in their learnings. Merge them into a unified KB.

```bash
# Project A exports
cd project-alpha
robo-cortex export --scope global --output kb_alpha.jsonl

# Project B also exports (has learned independently)
cd ../project-beta
robo-cortex export --scope global --output kb_beta.jsonl

# Merge both KBs (de-duplicates by ID, resolves conflicts by confidence)
robo-cortex merge kb_alpha.jsonl kb_beta.jsonl --output kb_merged.jsonl

# Result: kb_merged.jsonl has all unique learnings from both projects
```

### Conflict Resolution

If the same memory ID exists in both files:
- **Confidence wins**: Higher confidence version is kept
- **Tie-breaker**: Newer (later created_at) version wins
- **Verbose output**: Shows which version was chosen for each conflict

Example:
```bash
$ robo-cortex merge kb1.jsonl kb2.jsonl --output merged.jsonl

  🔄 Conflict at ID 3 (global): picked high over medium
  🔄 Conflict at ID 5 (global): confidence tie, picked new

✅ Merge complete:
   From kb1.jsonl: 10 memories
   From kb2.jsonl: 5 new memories
   Conflicts resolved: 2
   Total merged: 13 unique memories
```

### Complete Bidirectional Sync Workflow

**Scenario:** test-cortex learns 10 lessons, test2-cortex imports 10 + learns 3, test-cortex independently learns 2 more.

```bash
# Step 1: test-cortex exports initial learnings
cd /srv/test-cortex
robo-cortex export --scope global --output kb_v1.jsonl
# Contains: 10 lessons

# Step 2: test2-cortex imports + learns
cd /srv/test2-cortex
robo-cortex import kb_v1.jsonl
# Now has: 10 imported + learns 3 new = 13 total
robo-cortex export --scope global --output kb_v2.jsonl

# Step 3: test-cortex learns independently
cd /srv/test-cortex
# (learns 2 new lessons, total: 12 now)
robo-cortex export --scope global --output kb_v1_plus.jsonl
# Contains: 10 original + 2 new = 12 lessons

# Step 4: Merge both versions
robo-cortex merge kb_v1_plus.jsonl ../test2-cortex/kb_v2.jsonl --output kb_merged.jsonl
# Result: 10 + 2 + 3 = 15 unique lessons
# Handles conflicts (if same ID changed in both, picks higher confidence)

# Step 5: Both projects sync back
cd /srv/test-cortex
robo-cortex import kb_merged.jsonl
# Now has: 15 lessons (12 original + 3 new from test2)

cd /srv/test2-cortex
robo-cortex import kb_merged.jsonl
# Now has: 15 lessons (13 original + 2 new from test-cortex)
```

**Result:** Both projects converge to the same 15-lesson knowledge base. ✅

---

## FAQ

**Q: Can I export repo-scoped memories?**  
A: Yes, `robo-cortex export --scope repo`. But they're project-specific and usually shouldn't be shared. Share global scope for team KB.

**Q: What if I have 1000 memories?**  
A: Export handles any size. JSONL format is streamable. Importing is also safe (idempotent, no duplicates).

**Q: Can I edit the JSONL manually?**  
A: Yes! It's plain JSON. But be careful with IDs and required fields. Invalid JSON will be skipped on import with a warning.

**Q: Does export include evidence?**  
A: No. Export captures memory statements, status, confidence, but not attached evidence rows. Evidence is optional; reattach after import if needed.

**Q: How do I merge two KBs?**  
A: Concatenate JSONL files: `cat kb1.jsonl kb2.jsonl > kb_merged.jsonl`. Then import. Duplicates are auto-skipped.

---

**Export/import is the backbone of cross-project learning.** Start small (1 project), export learnings, import in project 2, watch knowledge compound over time. 📈
