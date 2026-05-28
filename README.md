```bash
# Create project directory
mkdir lms_convert && cd lms_convert

# Initialize uv project, assuming you already have uv installed
uv init

# Add the team repo as remote
git remote add origin https://github.com/Team-Delta/Team-Delta.git

# Pull
git pull origin main
# Note: 'uv init' creates some files within the directory and so pulling after 
# running it will require using the '--allow-unrelated-histories' flag or other
# overwrite options

# Now uv sync will read the pyproject.toml and setup everything
uv sync

# Install dev dependencies
uv sync --group dev
```
