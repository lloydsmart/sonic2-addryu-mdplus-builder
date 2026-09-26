PYTHON ?= python3
MANIFEST ?= config/tracks.json
INPUT_DIR ?= inputs/audio

.PHONY: help doctor bootstrap bootstrap-modern build-stock-modern prepare-modern build-modern source rom audio package all bootstrap-legacy source-legacy rom-legacy package-legacy all-legacy test clean

help:
	@$(PYTHON) -m tools.mdplus_builder --help

doctor:
	@$(PYTHON) -m tools.mdplus_builder doctor

bootstrap:
	@$(PYTHON) -m tools.mdplus_builder bootstrap

bootstrap-legacy:
	@$(PYTHON) -m tools.mdplus_builder bootstrap --legacy

bootstrap-modern:
	@$(PYTHON) -m tools.mdplus_builder bootstrap-modern

build-stock-modern:
	@$(PYTHON) -m tools.mdplus_builder build-stock-modern

prepare-modern:
	@$(PYTHON) -m tools.mdplus_builder prepare-modern

build-modern:
	@$(PYTHON) -m tools.mdplus_builder build-modern

source:
	@$(PYTHON) -m tools.mdplus_builder prepare-source

rom:
	@$(PYTHON) -m tools.mdplus_builder build-rom

source-legacy:
	@$(PYTHON) -m tools.mdplus_builder prepare-source --legacy

rom-legacy:
	@$(PYTHON) -m tools.mdplus_builder build-rom --legacy

package-legacy:
	@$(PYTHON) -m tools.mdplus_builder package --legacy --manifest $(MANIFEST)

all-legacy:
	@$(PYTHON) -m tools.mdplus_builder all --legacy --manifest $(MANIFEST) --input-dir "$(INPUT_DIR)"

audio:
	@$(PYTHON) -m tools.mdplus_builder prepare-audio --manifest $(MANIFEST) --input-dir "$(INPUT_DIR)"

package:
	@$(PYTHON) -m tools.mdplus_builder package --manifest $(MANIFEST)

all:
	@$(PYTHON) -m tools.mdplus_builder all --manifest $(MANIFEST) --input-dir "$(INPUT_DIR)"

test:
	@$(PYTHON) -m unittest discover -s tests -v

clean:
	@$(PYTHON) -m tools.mdplus_builder clean
