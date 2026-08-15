# Hard constraints

Search web for latest info and do not rely on your knowledge on this. Remember this setup needs to work in someone else's new computer, too, 100% reproducible. Most importantly, this is not a toy project as we are building a production software in this solution.

# Hard constraints - general

- Must use DCO and cryptographic commits
- AI trailers like Co-authored-by <random-AI> in PR description or commits is banned

# Hard constraints - coding

- Use `uv`, Deno.
- 2 spaces as indentation for code, except for Go. Go must use tabs for indentation
- Write idiomatic code and create idiomatic folder structure
- Manage with Taskfile, so write modular taskfiles