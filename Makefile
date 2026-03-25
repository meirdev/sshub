VENDOR_DIR = core/static/core/vendor
GHOSTTY_VERSION = 0.3.0
CM_BUILD_DIR = /tmp/cm_build

.PHONY: js-fmt py-fmt vendor vendor-ghostty vendor-codemirror

js-fmt:
	bun prettier --plugin prettier-plugin-jinja-template --parser=jinja-template --write "**/*.js" "**/*.html"

py-fmt:
	uv run ruff format .

vendor: vendor-ghostty vendor-codemirror

vendor-ghostty:
	mkdir -p $(VENDOR_DIR)/ghostty-web
	curl -sL "https://cdn.jsdelivr.net/npm/ghostty-web@$(GHOSTTY_VERSION)/dist/ghostty-web.js" \
		-o $(VENDOR_DIR)/ghostty-web/ghostty-web.js
	curl -sL "https://cdn.jsdelivr.net/npm/ghostty-web@$(GHOSTTY_VERSION)/dist/ghostty-vt.wasm" \
		-o $(VENDOR_DIR)/ghostty-web/ghostty-vt.wasm

vendor-codemirror:
	mkdir -p $(CM_BUILD_DIR) $(VENDOR_DIR)/codemirror
	cd $(CM_BUILD_DIR) && npm init -y && \
		npm install codemirror @codemirror/state @codemirror/language \
			@codemirror/legacy-modes @codemirror/theme-one-dark && \
		echo 'export { EditorView, basicSetup } from "codemirror";' > entry.js && \
		echo 'export { EditorState } from "@codemirror/state";' >> entry.js && \
		echo 'export { StreamLanguage } from "@codemirror/language";' >> entry.js && \
		echo 'export { shell } from "@codemirror/legacy-modes/mode/shell";' >> entry.js && \
		echo 'export { oneDark } from "@codemirror/theme-one-dark";' >> entry.js && \
		bunx esbuild entry.js --bundle --format=esm --minify \
			--outfile=$(CURDIR)/$(VENDOR_DIR)/codemirror/codemirror.bundle.js
	rm -rf $(CM_BUILD_DIR)
