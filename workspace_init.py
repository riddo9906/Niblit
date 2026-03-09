import os

def init_workspace():
    workspace_path = os.path.join(os.getcwd(), "ProjectOne")
    if not os.path.exists(workspace_path):
        os.makedirs(workspace_path)
    print(f"Workspace ready at: {workspace_path}")

if __name__ == "__main__":
    init_workspace()
