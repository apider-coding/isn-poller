<code>
git reset --hard tags/v1.0
git reset --hard
rm -rf .git/
git init
git add .
git commit -m 'first commit'
git remote add stash git@github.com:apider-coding/isn-poller.git
git push --force stash master<code>
