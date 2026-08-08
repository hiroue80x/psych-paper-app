#!/bin/bash
# ダブルクリックで起動します（初回のみ、右クリック→「開く」→「開く」で許可）。
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  python3 app.py
else
  echo ""
  echo "  Python3 が見つかりませんでした。"
  echo "  macOS の無料の開発ツール（Command Line Tools）をインストールします。"
  echo "  画面に出るウィンドウで「インストール」を押してください（数分かかります）。"
  echo ""
  xcode-select --install 2>/dev/null
  echo "  インストールが終わったら、もう一度この「起動.command」をダブルクリックしてください。"
  echo ""
  read -n 1 -s -r -p "  何かキーを押すと、このウィンドウを閉じます..."
fi
