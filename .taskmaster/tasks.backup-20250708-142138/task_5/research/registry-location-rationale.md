# Registry Location Decision Rationale

## Decision: `~/.pflow/registry.json`

### Why This Location?

1. **Standard Unix Convention**
   - Follows established patterns for application data storage
   - Users expect config/data in home directory dotfiles
   - Consistent with tools like `~/.docker/`, `~/.npm/`, etc.

2. **User-Specific Storage**
   - Each user maintains their own registry cache
   - No conflicts in multi-user systems
   - No elevated permissions required

3. **Future Compatibility**
   - When v2.0 adds user node installation, `~/.pflow/` will already exist
   - Natural location for future additions:
     - `~/.pflow/nodes/` - User-installed nodes
     - `~/.pflow/config.json` - User preferences
     - `~/.pflow/workflows/` - Saved workflows

4. **Easy Management**
   - Users can clear cache with `rm ~/.pflow/registry.json`
   - Backup/restore is straightforward
   - Version control friendly (can gitignore)

### Implementation Notes

- Create `~/.pflow/` directory if it doesn't exist
- Use `os.path.expanduser("~/.pflow")` for cross-platform compatibility
- Handle missing directory gracefully on first run
- Include timestamp in registry for cache invalidation

### Alternatives Considered

1. **Package data directory** - Would require reinstall to clear cache
2. **`/tmp/` directory** - Would rebuild on every reboot
3. **Working directory** - Would create clutter in user projects
4. **System location** - Would require sudo for updates

The `~/.pflow/` approach provides the best balance of convenience, convention, and future extensibility.
