# Port Development Data Team Repository

Welcome to the Port Development Data Team Repository. This guide is designed to help team members efficiently manage and contribute to the repository using Git and deploy Streamlit applications seamlessly.

## Getting Started with Git Locally

### if no SSH yet
1. open your bash terminal
2. ssh-keygen -t id_rse -C "your_email@example.com"
3. eval "$(ssh-agent -s)"
4. ssh-add ~/.ssh/id_rsa
5. cat ~/.ssh/id_rsa.pub | pbcopy
6. Log in to your GitHub account and go to the settings page. Navigate to "SSH and GPG keys" from the sidebar.
7. Click on “New SSH key”, give your key a title that helps you identify the machine the key is associated with, and paste the key into the "Key" field.
8. Click “Add SSH key” to save the new key.
9. Go back to your bash terminal and test if added correctly: ssh -T git@github.com


### If not cloned a repo yet
1. Open your bash terminal.
2. Start the SSH agent: `eval "$(ssh-agent -s)"`
3. Add your SSH key: `ssh-add ~/.ssh/id_rsa`
4. git clone your_SSH_repo_link

### if already cloned a repo
To begin working with Git locally, follow these steps to set up your environment:

1. Open your bash terminal.
2. Start the SSH agent: `eval "$(ssh-agent -s)"`
3. Add your SSH key: `ssh-add ~/.ssh/id_rsa`
4. Navigate to your repository's directory: `cd /path/to/your/repo`
5. Update your local repository: `git pull`
6. Add changes: `git add .`
7. Commit your changes with a message: `git commit -m "My new changes"`
8. Push your changes to the remote repository: `git push`

### Merging Branches

To merge changes from one branch (`branch_a`) into another (`branch_b`), follow these steps:

1. Fetch the latest changes: `git fetch origin`
2. Switch to the target branch: `git checkout branch_b`
3. Pull the latest updates: `git pull`
4. Merge the changes from `branch_a`: `git merge branch_a`
5. Add changes to the staging area: `git add .`
6. Commit the merge: `git commit -m "Merges branch_a into branch_b"`
7. Push the merge to the remote repository: `git push`

## Deploying Streamlit Apps

To deploy a Streamlit application, ensure you're in the directory containing the `.env` file and follow these steps:

1. Activate your environment variables: `for /f "tokens=1* delims==" %i in ('type .env') do @set %i=%j`
2. Verify the activation: `echo $ENV_VAR`
3. Navigate to the Streamlit app directory.
4. Set the server with: `rsconnect add --server "https://prod.cdl.azr.ad.portofrotterdam.com/rsc" --api-key ${API_KEY} --insecure --name "prod"`
5. Deploy the app using the appropriate command below, replacing `!!REPLACE name_app!!` with your application's name.

- Primary deployment command:  
    ```
    rsconnect deploy streamlit --title "contract_chatbot" --name "prod" --entrypoint app.py --environment DATABRICKS_TOKEN=${DATABRICKS_TOKEN} --environment DATABRICKS_HTTP_PATH=${DATABRICKS_HTTP_PATH} --environment DATABRICKS_SERVER_HOSTNAME=${DATABRICKS_SERVER_HOSTNAME} ./
    ```

- Alternative deployment options are available for different app configurations. Please refer to the specific commands for your scenario.

## Environment Management

For managing Python dependencies and environments, use the following instructions:

- To create a `requirements.txt` file: `pip list --format=freeze > requirements.txt`
- To create a new conda environment: `conda create --name envname`
- To clone an existing conda environment: `conda create --name myclone --clone myenv`
    - Replace `myclone` with the new environment's name and `myenv` with the existing environment's name.
- To install a specific version of databricks-connect: `pip install databricks-connect==13.2`
    - Choose the correct databricks-connect version based on your compute performance requirements.
- To remove a conda environment: `conda remove --name ENV_NAME --all`
- To activate environment variables (if not set): Navigate to the directory containing your `.env` file and activate the variables with: `for /f "tokens=1* delims==" %i in ('type .env') do @set %i=%j`

## Additional Information

- To configure Streamlit's appearance, adjust the settings in the `.streamlit/config.toml` file according to your preferences:

    ```
    [theme]
    base = "Dark"
    primaryColor = "#0ecdf1"
    backgroundColor = "#061941"
    secondaryBackgroundColor = "#a4a4af"
    ```

This guide aims to streamline your development workflow and application deployment process. If you have any questions or need further assistance, please reach out to the team.
