#!/bin/bash

# Ablation study runner using tmux for parallel execution

# Check if tmux is installed
if ! command -v tmux &> /dev/null; then
    echo "tmux is not installed. Please install tmux first."
    exit 1
fi

SESSION_NAME="ds"

# Check if session already exists and kill it if it does
if tmux has-session -t $SESSION_NAME 2>/dev/null; then
    echo "Session '$SESSION_NAME' already exists. Killing it..."
    tmux kill-session -t $SESSION_NAME
    sleep 1  # Wait a moment for the session to be killed
fi

# Create tmux session
tmux new-session -d -s $SESSION_NAME

# Create windows for each ROUND setting
tmux new-window -t $SESSION_NAME:1 -n round1
tmux new-window -t $SESSION_NAME:2 -n round2
tmux new-window -t $SESSION_NAME:3 -n round3
tmux new-window -t $SESSION_NAME:4 -n round4

# Send commands to each window
echo "Setting up ablation study in tmux session: $SESSION_NAME"

# Round 1
tmux send-keys -t $SESSION_NAME:1 "echo 'Starting ablation study - Round 1'; DISABLE_KG=true ROUND=deepseek-v3_round_c_1 uv run run_ablation.py" Enter

# Round 2
tmux send-keys -t $SESSION_NAME:2 "echo 'Starting ablation study - Round 2'; DISABLE_KG=true ROUND=deepseek-v3_round_c_2 uv run run_ablation.py" Enter

# Round 3
tmux send-keys -t $SESSION_NAME:3 "echo 'Starting ablation study - Round 3'; DISABLE_KG=true ROUND=deepseek-v3_round_c_3 uv run run_ablation.py" Enter

# Round 4
tmux send-keys -t $SESSION_NAME:4 "echo 'Starting ablation study - Round 4'; DISABLE_KG=true ROUND=deepseek-v3_round_c_4 uv run run_ablation.py" Enter

echo "Ablation study started in tmux session '$SESSION_NAME'"
echo ""
echo "To attach to the session, run:"
echo "  tmux attach -t $SESSION_NAME"
echo ""
echo "To view specific windows:"
echo "  tmux attach -t $SESSION_NAME:1  (Round 1)"
echo "  tmux attach -t $SESSION_NAME:2  (Round 2)"
echo "  tmux attach -t $SESSION_NAME:3  (Round 3)"
echo "  tmux attach -t $SESSION_NAME:4  (Round 4)"
echo ""
echo "To detach from the session, press Ctrl+B then D"
echo ""
echo "To kill the session, run:"
echo "  tmux kill-session -t $SESSION_NAME"