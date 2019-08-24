LOG_DIR=/var/log/garage
DB_DIR=/var/local/garage

.PHONY: deb dist install uninstall clean run sql

deb: garage.deb

garage.deb: Makefile dist dist/DEBIAN/*
	fakeroot dpkg-deb --build dist garage.deb

dist:
	git rev-parse HEAD >dist/opt/garage/git_rev
	chmod -R go-w dist

install: garage.deb
	@# We specify confmiss and confnew because we don't want deployment
	@# to ever halt to ask us, and in general we don't modify config files
	@# in a way that we want to keep. Modifications or deletions are temporary
	@# changes that we always want to overwrite with new deploys. Note that
	@# confnew does not always overwrite changes to config files. If the
	@# new package's file is the same as the old package's, then the conf
	@# file isn't touched at all and changes are kept. If you've made changes
	@# to a config file and want it reverted, delete the file altogether
	@# before deployment.
	sudo dpkg --install --force-confmiss,confnew garage.deb

uninstall:
	sudo dpkg --purge garage

clean:
	rm -f garage.deb dist/opt/garage/git_rev

prepare:
	sudo mkdir -p $(LOG_DIR) $(DB_DIR)

# Runs in situ, for debugging.
run: dist
	cd dist/opt/garage; sudo python garage.py --port=8889

sql:
	@psql -U garage -d garage
