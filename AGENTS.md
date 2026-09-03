# Hard constraints - general

- Search web for latest info and do not rely on your knowledge on this 
- Remember this setup needs to work in someone else's new computer, too, 100% reproducible
- Most importantly, this is not a toy project as we are building a production software in this solution
- Git merging to remote on your own is fully banned
- Git commit or push when the operator explicitly asks so
- Must use DCO and cryptographic commits
- AI trailers like Co-authored-by <random-AI> in PR description or commits is fully banned

# Hard constraints - coding

- Use `uv`
- Use Ansible for provider and infrastructure lifecycle automation (Task entrypoints invoke Ansible playbooks/roles; do not bypass Ansible with ad-hoc host scripts for those lifecycles).
- 2 spaces as indentation for code, except for Go. Go must use tabs for indentation
- Write idiomatic code and create idiomatic folder structure
- Manage with Taskfile, so write modular taskfiles

# Hard constraints - Solution and ticket design

- Design pragmatic, production-safe infrastructure for hosting business applications—not bank-grade systems. Prefer the smallest maintainable solution built from existing project and upstream primitives; avoid speculative hardening, duplicate mechanisms, compatibility layers without a current need, and unrelated scope.
- Treat proven working subsystems—especially the existing WireGuard + Lima foundation—as frozen behavior. Integrate only through the smallest adapter, add characterization/parity tests before changing a consumer, and reject adjacent-ticket edits to their ownership, lifecycle, networking, firewall, or cleanup; any unavoidable redesign requires its own explicit operator-approved issue.
- Before proposing work, inspect the current code and active documentation
