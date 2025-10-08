#!/bin/bash

# Models to test
models=("llama3.1:8b" "mistral:7b" "codellama:7b")
OLLAMA_HOST=192.168.100.10

# echo "=== Pulling Models ==="
# for model in "${models[@]}"; do
#   echo "Pulling $model..."
#   curl -X POST http://${OLLAMA_HOST}:11434/api/pull \
#     -H "Content-Type: application/json" \
#     -d "{
#       \"name\": \"$model\",
#       \"stream\": false
#     }"
  
#   # Check if pull was successful
#   if [ $? -eq 0 ]; then
#     echo "✓ Successfully pulled $model"
#   else
#     echo "✗ Failed to pull $model"
#     exit 1
#   fi
#   echo ""
# done

echo "=== Pulling Models with Progress ==="
for model in "${models[@]}"; do
  echo "Pulling $model..."
  
  # Pull with streaming to see progress
  curl -X POST http://${OLLAMA_HOST}:11434/api/pull \
    -H "Content-Type: application/json" \
    -d "{
      \"name\": \"$model\",
      \"stream\": true
    }" | while IFS= read -r line; do
    # Parse JSON and show progress
    status=$(echo "$line" | jq -r '.status // empty')
    completed=$(echo "$line" | jq -r '.completed // empty')
    total=$(echo "$line" | jq -r '.total // empty')
    
    if [[ -n "$status" ]]; then
      if [[ -n "$completed" && -n "$total" ]]; then
        percent=$((completed * 100 / total))
        echo "  $status: $percent%"
      else
        echo "  $status"
      fi
    fi
  done
  
  echo "✓ Finished pulling $model"
  echo ""
done


echo "=== Pre-loading Models ==="
for model in "${models[@]}"; do
  echo "Loading $model into memory..."
  curl -s -X POST http://${OLLAMA_HOST}:11434/api/generate \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"$model\",
      \"prompt\": \"\",
      \"stream\": false,
      \"keep_alive\": \"2h\"
    }" > /dev/null
  
  if [ $? ]; then
    echo "✓ $model loaded and ready"
  else
    echo "✗ Failed to load $model"
  fi
done

echo ""
echo "=== Checking Loaded Models ==="
curl -s http://${OLLAMA_HOST}:11434/api/ps | jq '.'

echo ""
echo "=== Testing Model Switching ==="
for i in {1..3}; do
  echo "Test round $i:"
  for model in "${models[@]}"; do
    echo "  Testing $model..."
    response=$(curl -s -X POST http://${OLLAMA_HOST}:11434/api/generate \
      -H "Content-Type: application/json" \
      -d "{
        \"model\": \"$model\",
        \"prompt\": \"Say hello in one word\",
        \"stream\": false,
        \"keep_alive\": \"2h\"
      }")
    
    if [ $? ]; then
      # Extract just the response text
      echo "    Response: $(echo "$response" | jq -r '.response' | tr -d '\n')"
    else
      echo "    ✗ Failed to get response from $model"
    fi
  done
  echo ""
done

echo "=== Final Status ==="
curl -s http://${OLLAMA_HOST}:11434/api/ps | jq '.'