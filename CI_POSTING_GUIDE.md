# CI/CD LinkedIn Posting Guide

## The Problem

LinkedIn posting often fails in CI/CD environments (like GitHub Actions) due to:

1. **Network timeouts** - LinkedIn may be slow or unreachable from CI servers
2. **IP blocking** - LinkedIn blocks many cloud/CI IP ranges to prevent automation
3. **Security challenges** - LinkedIn may require CAPTCHA verification for new IPs
4. **Browser limitations** - Headless browsers in CI may behave differently

## Solutions

### Option 1: Disable Posting in CI (Recommended)

The safest approach is to generate content in CI but post manually:

```bash
# In your CI environment variables
ENABLE_POST=false
```

This will:
- ✅ Generate content and save it locally
- ✅ Run all validation and SEO checks  
- ✅ Create preview files for manual review
- ❌ Skip actual LinkedIn posting

### Option 2: Use Dry-Run Mode

Run the agent with `--dry-run` flag:

```bash
python run.py --force --dry-run
```

### Option 3: Test Locally First

Before deploying to CI, test your setup locally:

```bash
# Test LinkedIn connection
python test_linkedin_connection.py

# Test full workflow locally
python run.py --dry-run --force
```

### Option 4: Enable CI Posting (Advanced)

If you want to attempt posting in CI:

1. Set `ENABLE_POST=true` in your repository secrets
2. Use shorter timeouts for CI:
   ```
   LINKEDIN_LOGIN_NAV_TIMEOUT_MS=60000
   LINKEDIN_DEFAULT_TIMEOUT_MS=30000
   ```
3. Accept that posting may fail intermittently

## Current CI Configuration

The GitHub Actions workflow is configured to:

- **Default**: `ENABLE_POST=false` (content generation only)
- **Override**: Set `ENABLE_POST=true` in repository secrets to enable posting
- **Fallback**: If posting fails, the workflow continues (doesn't fail the build)

## Troubleshooting

### Timeout Errors
```
Page.goto: Timeout 300000ms exceeded
```

**Solutions:**
- Reduce timeout values for CI
- Use `ENABLE_POST=false`
- Test locally first

### Authentication Errors
```
LinkedIn authentication failed
```

**Solutions:**
- Verify credentials work locally
- Check for security challenges
- Use session storage state files

### Network Errors
```
Failed to setup browser
```

**Solutions:**
- Check CI network connectivity
- Use `--dry-run` mode
- Disable posting in CI

## Best Practices

1. **Always test locally** before deploying to CI
2. **Use content generation** in CI, manual posting locally
3. **Set up monitoring** for failed CI runs
4. **Keep credentials secure** using repository secrets
5. **Have fallback strategies** when posting fails

## Example Workflow

```yaml
# Recommended CI workflow
- name: Generate Content
  env:
    ENABLE_POST: false
  run: python run.py --force --dry-run

- name: Attempt Posting (Optional)
  if: ${{ secrets.ENABLE_POST == 'true' }}
  run: |
    python run.py --force || {
      echo "Posting failed - content saved for manual review"
      exit 0
    }
```

This approach ensures your CI pipeline is reliable while still generating valuable content.