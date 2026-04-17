#!/bin/bash

set -e

ENV_FILE=".devcontainer/devcontainer.env"

echo "Ensuring devcontainer.env has valid AWS credentials..."

# If env file exists, check remaining validity and reuse if > 1 hour left
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    if [ ! -z "$AWS_CREDENTIAL_EXPIRATION" ] && [ "$AWS_CREDENTIAL_EXPIRATION" != "null" ]; then
        NOW_EPOCH=$(date -u +%s)
        EXPIRY_EPOCH=$(date -d "$AWS_CREDENTIAL_EXPIRATION" +%s 2>/dev/null || echo 0)
        if [ "$EXPIRY_EPOCH" -gt 0 ]; then
            SECONDS_LEFT=$(( EXPIRY_EPOCH - NOW_EPOCH ))
            ONE_HOUR=3600
            if [ $SECONDS_LEFT -gt $ONE_HOUR ]; then
                HOURS_LEFT=$(awk -v s=$SECONDS_LEFT 'BEGIN { printf "%.2f", s/3600 }')
                echo "✅ Existing credentials valid for another ~${HOURS_LEFT}h (>=1h). Skipping refresh."
                exit 0
            else
                echo "ℹ️ Credentials expiring soon (<=1h left). Refreshing..."
            fi
        else
            echo "⚠️ Could not parse existing AWS_CREDENTIAL_EXPIRATION. Refreshing credentials..."
        fi
    else
        echo "ℹ️ No expiration info found in existing env file. Refreshing credentials..."
    fi
fi

# Check if AWS CLI is available
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI is not installed. Please install AWS CLI first."
    exit 1
fi

AWS_PROFILE="ok-ki-prod-origo-bedrock-inference-access"

# Get AWS credentials using AWS CLI
echo "Fetching AWS credentials..."

aws sso login --profile "$AWS_PROFILE"

# Export credentials using AWS CLI configure export-credentials
echo "Using AWS profile: $AWS_PROFILE"

# Export credentials in env format
CREDENTIALS_OUTPUT=$(aws configure export-credentials --profile "$AWS_PROFILE" --format env)

if [ $? -ne 0 ]; then
    echo "Error: Failed to export credentials for profile $AWS_PROFILE"
    echo "Make sure the profile exists and is properly configured."
    exit 1
fi

# Parse the exported credentials
eval "$CREDENTIALS_OUTPUT"

# Get default region from the profile
AWS_DEFAULT_REGION=eu-south-2

# Create the env file with exported credentials
cat > "$ENV_FILE" << EOF
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION
EOF

# Add session token if available
if [ ! -z "$AWS_SESSION_TOKEN" ] && [ "$AWS_SESSION_TOKEN" != "null" ]; then
    echo "AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN" >> "$ENV_FILE"
fi

# Add credential expiration if available
if [ ! -z "$AWS_CREDENTIAL_EXPIRATION" ] && [ "$AWS_CREDENTIAL_EXPIRATION" != "null" ]; then
    echo "AWS_CREDENTIAL_EXPIRATION=$AWS_CREDENTIAL_EXPIRATION" >> "$ENV_FILE"
fi

echo "✅ devcontainer.env created successfully"

# Format the ISO timestamp nicely for display
FORMATTED_EXPIRATION=$(date -d "$AWS_CREDENTIAL_EXPIRATION" '+%Y-%m-%d at %H:%M:%S UTC' 2>/dev/null || echo "$AWS_CREDENTIAL_EXPIRATION")
echo "🕒 Credentials will expire on: $FORMATTED_EXPIRATION"

# Ensure the env file is in .gitignore
GITIGNORE_FILE=".gitignore"
if [ -f "$GITIGNORE_FILE" ]; then
    if ! grep -q "devcontainer.env" "$GITIGNORE_FILE"; then
        echo ".devcontainer/devcontainer.env" >> "$GITIGNORE_FILE"
        echo "✅ Added devcontainer.env to .gitignore"
    fi
else
    echo ".devcontainer/devcontainer.env" > "$GITIGNORE_FILE"
    echo "✅ Created .gitignore and added devcontainer.env"
fi
