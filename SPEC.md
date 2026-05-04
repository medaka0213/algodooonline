# Algodoo Online 移行仕様書

この文書は、`../Algon2-APP` と `../Algon2-API` から読み取れる既存仕様を、Python + uv モノレポ実装の受け入れ条件として固定するための仕様書です。

このリポジトリの実装が完成しているかは、この文書の「移行後の必須条件」と「ローカル結合試験条件」で判定します。現在の実装や一時的な足場を仕様の根拠にしてはいけません。

## 1. 参照元

旧実装の一次情報は以下です。

- 旧フロント: `../Algon2-APP`
- 旧API: `../Algon2-API`
- 旧フロントの画面ルート: `../Algon2-APP/src/App.js`
- 旧フロントの共通レイアウト: `../Algon2-APP/src/components/04_Templates/MainTemplate.js`
- 旧フロントのNavbar: `../Algon2-APP/src/components/01_Atoms/parts/Navbar.js`
- 旧フロントのホーム: `../Algon2-APP/src/components/05_Pages/Home.js`
- 旧フロントの掲示板一覧: `../Algon2-APP/src/components/05_Pages/BBSListPage.js`
- 旧フロントの掲示板詳細: `../Algon2-APP/src/components/05_Pages/BBSDetailPage.js`
- 旧フロントの投稿フォーム: `../Algon2-APP/src/components/02_Molecules/Forms/ThreadForm.js`
- 旧フロントの返信フォーム: `../Algon2-APP/src/components/02_Molecules/Forms/LogForm.js`
- 旧フロントの認証: `../Algon2-APP/src/actions/auth.js`
- 旧フロントの認証画面: `../Algon2-APP/src/components/05_Pages/*Page.js`
- 旧フロントのAPI呼び出し: `../Algon2-APP/src/actions/fetch/*.js`
- 旧フロントのバリデーション: `../Algon2-APP/src/actions/form/validationSchema.js`
- 旧APIルート: `../Algon2-API/app.py`
- 旧APIのDynamoDB構成: `../Algon2-API/chalicelib/db.py`
- 旧APIの投稿・集計ロジック: `../Algon2-API/chalicelib/post.py`
- 旧APIのサーバー側バリデーション: `../Algon2-API/chalicelib/schema.py`
- 旧APIのファイル保存: `../Algon2-API/chalicelib/file.py`, `../Algon2-API/chalicelib/s3.py`, `../Algon2-API/chalicelib/phz.py`

## 2. 移行方針

移行後のアプリは、ユーザーから見える仕様を維持したうえで、実装方式を現代化します。

- 旧 React + Chalice を Python + uv モノレポに統合する。
- 画面とAPIは Python 側で管理する。FastAPI + Jinja2 を基本とし、必要が出るまでReact等のフロントビルドを追加しない。
- DynamoDBは維持する。
- DynamoDBのアクセス層は `DynamoDB-SingleTable` を使う。
- `DynamoDB-SingleTable` は別リポジトリなので、このリポジトリにvendoringしてコミットしない。
- 旧DynamoDBの4テーブル構成からsingle-tableへ移行できるように、ID・旧v1属性・移行状態を保持する。
- デプロイ先はAWSサーバーレスかつ従量課金前提にする。
- ローカルでは Docker Compose だけで画面・認証代替・DynamoDB互換ストア・APIの結合試験を完結させる。

推奨AWS構成は以下です。

- FastAPI app: AWS Lambda + Mangum
- 公開入口: Lambda Function URL または API Gateway HTTP API
- 認証: Amazon Cognito User Pool
- DB: DynamoDB on-demand
- ファイル: S3
- 静的配信が必要な場合: CloudFront + S3。ただしSSR中心なら必須ではない。
- ローカルDynamoDB互換: Docker Compose 内の DynamoDB Local または moto。アプリコードは本番と同じ `boto3 + ddb_single` 経由にする。

## 3. ルートと掲示板種別

旧フロントの正規画面ルートは `../Algon2-APP/src/App.js` にある通りです。

| 画面 | 旧正規パス | 移行後の必須対応 |
| --- | --- | --- |
| ホーム | `/` | 必須 |
| 掲示板一覧 | `/i/:route` | 必須 |
| 掲示板詳細 | `/i/:route/:thread_id` | 必須 |
| サインアップ | `/auth/signup`, `/auth/signup/:Username` | 必須 |
| ログイン | `/auth/login` | 必須 |
| ログアウト | `/auth/logout` | 必須 |
| パスワード変更 | `/auth/changepass` | 必須 |
| パスワード忘れ | `/auth/forgotpass` | 必須 |
| 不明なURL | fallbackで `/` | 必須 |

掲示板種別は旧APIの `ThreadSchema.route` と旧ホーム画面から以下4つです。

| route | ホーム表示名 | 振る舞い |
| --- | --- | --- |
| `BBS` | `BBS掲示板` | プレーンテキスト投稿 |
| `WIKI` | `Wiki` | Markdown投稿 |
| `IMAGE` | `画像掲示板` | Markdown投稿、画像アップロード、画像スライド表示 |
| `DATA` | `Phz/Phnデータ掲示板` | Markdown投稿、PHZ/PHNアップロード、サムネイルとダウンロード |

旧Navbarのサイトマップは `/BBS`, `/Wiki`, `/Image`, `/Data` を指していますが、旧React Routerは `/i/:route` しか定義していません。移行後は旧正規パス `/i/BBS` 等を必須としつつ、壊れたリンクを残さないため `/BBS`, `/Wiki`, `/Image`, `/Data` を `/i/BBS`, `/i/WIKI`, `/i/IMAGE`, `/i/DATA` へリダイレクトする互換対応を持つこと。

## 4. 共通画面仕様

### 4.1 レイアウト

旧 `MainTemplate` は全画面で以下の構成です。

- 最上部にNavbar。
- 本文は `container p-3 border-right border-left`。
- `BreadcrumbRoutes` が渡された画面ではパンくずを表示。
- ホームはパンくずなし。
- 認証画面は本文中に `col-md-4 offset-md-4 bg-light mt-4 p-4 border` の狭いカードを置く。

移行後も、画面幅・余白・罫線・Bootstrap 4系の軽い見た目を維持すること。現代化しても、管理画面風・ダッシュボード風・ドキュメントページ風に変えてはいけない。

### 4.2 Navbar

旧Navbarの仕様は以下です。

- 背景は `light`。
- ブランド文言は `AlgodooOnline [ver 2.0]`。
- 左側に `サイトマップ` ドロップダウン。
- サイトマップ項目は `ホーム`, `掲示板`, `Wiki`, `画像`, `データ`。
- 未ログイン時は右側に `ユーザー認証` リンクを表示し、`/auth/login` へ遷移する。
- ログイン時は右側に `Hello, {user_info.name}!` ドロップダウンを表示する。
- ログイン時ドロップダウンの項目は `ログアウト`, `パスワードを変更`。

### 4.3 パンくず

旧Breadcrumbの仕様は以下です。

- 先頭は必ず `ホーム` で `/` へリンクする。
- 掲示板一覧は `ホーム / {route}`。
- 掲示板詳細は `ホーム / {route} / {thread.title}`。
- 中間routeには `/i/{route}` のリンクを付ける。
- 現在位置はactive表示にする。

### 4.4 ホーム

旧ホーム `/` の仕様は以下です。

- `AlgodooOnline` を中央寄せ、32px相当、太字、オレンジで表示する。
- ログイン時は `ユーザー: {name} ({sub})` を表示する。
- 未ログイン時は `ログインしてください` を表示する。
- 中央のナビゲーション枠に以下4リンクを表示する。
- `/i/BBS` -> `BBS掲示板`
- `/i/WIKI` -> `Wiki`
- `/i/IMAGE` -> `画像掲示板`
- `/i/DATA` -> `Phz/Phnデータ掲示板`
- `.index-nav` は薄い枠、余白あり。
- `.index-list` は薄い枠のカード風リンクで、hover時に半透明になる。

## 5. 認証仕様

旧実装は Cognito User Pool を使います。ローカルではCognito本体を使わず代替セッションでもよいが、画面・遷移・ログイン必須箇所は旧仕様を満たすこと。本番ではCognitoを使う。

### 5.1 認証状態

旧 `user_info` state は以下を持ちます。

- `name`
- `sub`
- `idToken`
- `refreshToken`
- `refreshTokenExp`
- `status`

ログイン判定は以下です。

- `idToken` がない場合は未ログイン。
- `idToken` が失効間近なら `refreshToken` で更新する。
- `refreshToken` も失効間近なら未ログイン。

移行後はサーバー側セッションに置き換えてよいが、画面上のログイン・未ログイン分岐は同じにする。

### 5.2 ログイン画面 `/auth/login`

旧ログイン画面の仕様は以下です。

- 認証カード内に表示する。
- 見出しは `ログインする`。
- 入力は `ユーザー名`, `パスワード`。
- 送信ボタンは `Log in`。
- 下部リンクは `アカウントを新規作成する` と `パスワードを忘れた場合`。
- ログイン成功後は `/` へリダイレクトする。
- ログイン前に `/user/signin` で旧v1ユーザーか判定する。
- `isV1` の場合は「認証方式が更新されました。」の案内を出し、`/auth/signup/{v1_name}` へ誘導する。
- v2ユーザーの場合はCognitoログインし、成功後 `/user/update` でDBのユーザー情報を更新する。

### 5.3 サインアップ画面 `/auth/signup`, `/auth/signup/:Username`

旧サインアップ画面の仕様は以下です。

- 見出しは `アカウントを新規作成`。
- 入力は `ユーザー名`, `メールアドレス`, `パスワード`, `パスワード(確認用)`。
- `:Username` がある場合はユーザー名を固定表示し、入力欄にはしない。
- 送信ボタンは `仮登録する(検証コード送信)`。
- 仮登録後は検証コード入力画面に切り替える。
- 検証コード画面の説明は `メールアドレスに送信された検証コードを入力して、ユーザー登録を完了してください`。
- 入力は `ユーザー名`, `確認コード`。
- 送信ボタンは `本登録`。
- 本登録成功後は `/auth/login` へリダイレクトする。

### 5.4 ログアウト画面 `/auth/logout`

旧ログアウト画面の仕様は以下です。

- 未ログイン時は `/` へリダイレクトする。
- 見出しは `ログアウトする`。
- 説明は `下のボタンを押すとログアウトします`。
- ボタンは赤系の `Log Out`。
- 押下でログアウトする。

### 5.5 パスワード変更 `/auth/changepass`

旧パスワード変更画面の仕様は以下です。

- 見出しは `パスワードを変更する`。
- 入力は `ユーザー名`, `パスワード`, `新しいパスワード`, `新しいパスワード (確認用)`。
- 送信ボタンは `パスワードを変更`。
- 成功後は `/` へリダイレクトする。

### 5.6 パスワード忘れ `/auth/forgotpass`

旧パスワード忘れ画面の仕様は以下です。

- 初期画面の見出しは `パスワードを忘れた場合`。
- 入力は `ユーザー名`。
- 送信ボタンは `検証コードを送る`。
- 送信成功後は回復フォームに切り替える。
- 回復フォーム説明は `メールアドレスに送信された検証コードを入力して、パスワードを回復してください`。
- 入力は `検証コード`, `新しいパスワード`, `新しいパスワード(確認用)`。
- 送信ボタンは `パスワードを変更する`。
- 成功後は `/` へリダイレクトする。

### 5.7 認証必須箇所

旧画面では以下がログイン必須です。

- スレッド投稿フォーム。
- ログ投稿フォーム。
- ログへの返信フォーム。
- スレッド編集・削除。
- ログ編集・削除。
- Like投稿・削除。
- 自分のLike状態取得。
- `/auth/logout`, `/auth/changepass`。

未ログイン時に投稿フォーム相当を開いた場合は `ログインしてください` リンクを表示し、`/auth/login` へ遷移できること。

## 6. 掲示板一覧仕様 `/i/:route`

旧 `BBSListPage` の画面構成は以下の順番です。

1. 共通Navbar。
2. パンくず `ホーム / {route}`。
3. `スレッドを投稿する` ボタン。
4. スレッド投稿モーダル。
5. 検索・並べ替えフォーム。
6. スレッド一覧。

初期表示時に `GET /threads/{route}` を呼び、結果を `updated_at` 新しい順に並べる。

### 6.1 スレッド一覧アイテム

旧 `ThreadListItem` の仕様は以下です。

- 各アイテムは上下罫線付きの横レイアウト。
- `IMAGE` は左に画像プレビューを表示する。
- `DATA` は左にPHZサムネイルを表示する。
- その右にLike表示を置く。
- メイン領域にタイトル、投稿情報、本文抜粋を表示する。
- クリック領域全体が `/i/{route}/{thread_id}` へのリンクになる。
- タイトルは太字のh3相当。
- 投稿情報は `user_name`, `返信: {nRes}件`, `updated_at` の相対時刻, 編集済み表示。
- 本文は通常140文字で省略し、末尾に `...` を付ける。
- 検索後はマッチ箇所を黄色背景でハイライトし、抜粋表示する。
- `isDeleted` または検索非マッチで `disabled` になったアイテムは表示しない。

## 7. 掲示板詳細仕様 `/i/:route/:thread_id`

旧 `BBSDetailPage` の画面構成は以下の順番です。

1. 共通Navbar。
2. パンくず `ホーム / {route} / {thread.title}`。
3. スレッド本文ブロック。
4. `このスレッドに返信する` ボタン。
5. ログ投稿モーダル。
6. 検索・並べ替えフォーム。
7. ログ一覧。

初期表示時に `GET /threads/{route}/{thread_id}` を必ず呼ぶ。ログ一覧 `GET /bbslogs/{thread_id}` は旧実装ではログイン時のみ呼ぶ。移行後も少なくとも投稿フォームは未ログイン時にログイン誘導を出すこと。ログ本文を未ログインに公開するかは旧コード上ではログイン時のみ取得だったため、互換優先なら未ログインではログ一覧を表示しない。

### 7.1 スレッド本文ブロック

旧 `ThreadInfoBlock` / `ThreadInfoBody` の仕様は以下です。

- `DATA` routeでは本文の前にPHZ/PHNダウンロードブロックを表示する。
- スレッドタイトルをh1相当で太字表示する。
- 左にLike表示、右に本文を表示する。
- 投稿情報は `user_name`, `返信: {nRes}件`, 相対更新時刻, 編集済み表示。
- 投稿者本人の場合のみ `menu` ドロップダウンを表示する。
- ドロップダウン項目は `投稿を編集`, `投稿を削除`。
- `WIKI`, `IMAGE`, `DATA` はMarkdownとして本文表示する。
- `BBS` はプレーンテキストとして表示し、改行と長い単語折返しを維持する。
- `IMAGE` routeでは本文の後に画像スライドショーを表示する。

### 7.2 ログ一覧

旧 `LogListBlock` / `LogItem` の仕様は以下です。

- ルートログは `response_to` が空で `disabled` ではないものだけを表示する。
- 各ログは上罫線付き。
- 削除済みログは本文の代わりに `この返信は削除されました` と薄い文字で表示する。
- 通常ログは左にLike表示、右にログ本文、本人なら `menu` を表示する。
- ログ本文はクリックで `このログに返信する` モーダルを開ける。
- ログの返信は親ログの下に左罫線付きインデントで表示する。
- 返信は初期状態では `N件の返信` のリンクだけを表示し、クリック後に展開する。
- 返信ログ自体も同じ `LogItem` として表示する。

### 7.3 ログ編集・削除

旧 `LogDropdown` の仕様は以下です。

- 本人のログのみ `menu` を表示する。
- 項目は `ログを編集`, `ログを削除`。
- 編集モーダルのタイトルは `ログを編集する`。
- 削除モーダルのタイトルは `ログを削除する`。

削除フォームはスレッド・ログ共通で、削除実行前に以下を要求する。

- 説明文: `投稿を削除するには、「削除」または「delete」と入力してください`
- 入力値が `削除` または `delete` の場合のみ送信できる。

## 8. 投稿フォーム仕様

### 8.1 スレッド投稿

旧 `ThreadForm` の仕様は以下です。

- モーダル起動ボタンの標準文言は `スレッドを投稿する`。
- モーダルサイズは大きめ。
- 未ログイン時はフォームではなく `ログインしてください` リンク。
- 入力は `title`, `content`。
- `WIKI`, `IMAGE`, `DATA` ではMarkdownエディタを使う。
- `BBS` では通常textareaを使う。
- `IMAGE` では画像ドロップゾーンを表示する。
- `DATA` ではPHZ/PHNドロップゾーンを表示する。
- ドロップゾーン文言は `ファイルをドラッグ＆ドロップ` と `またはクリックして選択`。
- `IMAGE` のファイルはクライアント側でJPEG Data URLへ変換し、複数添付できる。
- `DATA` のファイルはPHZ/PHNとしてData URLへ変換し、1件を添付する。
- PHZの場合はzip内 `thumb.png` を読み出し、サムネイル表示に使う。
- 選択ファイル数とファイル名一覧を表示する。
- 送信ボタンは `submit`。

送信bodyは旧API互換として以下です。

```json
{
  "submition": {
    "title": "title",
    "user_name": "name",
    "user_id": "sub",
    "content": "content",
    "filedata": []
  }
}
```

編集時は以下です。

```json
{
  "submition": {
    "title": "title",
    "content": "content"
  }
}
```

### 8.2 ログ投稿・返信

旧 `LogForm` の仕様は以下です。

- スレッドへの返信モーダル起動ボタンの標準文言は `このスレッドに返信する`。
- ログへの返信モーダルタイトルは `このログに返信する`。
- 未ログイン時は `ログインしてください` リンク。
- 入力は `content` textarea。
- 送信ボタンは `Submit`。

通常ログ投稿bodyは以下です。

```json
{
  "submition": {
    "user_name": "name",
    "user_id": "sub",
    "content": "content"
  }
}
```

ログ返信は同じbodyを `POST /bbslogs/{thread_id}/{log_id}` に送る。ログ編集は以下です。

```json
{
  "submition": {
    "content": "content"
  }
}
```

## 9. 検索・並べ替え仕様

旧 `SearchForm` の仕様は以下です。

- 検索欄は横長入力 + `Submit` ボタン。
- placeholderは旧コード上では常に `返信を検索する` になっている。
- 並べ替えselectは `w-50`。
- 選択肢は以下。
- `並べ替え` -> 値なし。
- `新着 (更新日時)` -> `NEWEST_UPDATED`。
- `新着 (投稿日時)` -> `NEWEST_CREATED`。
- `古い順 (更新日時)` -> `OLDEST_UPDATED`。
- `古い順 (投稿日時)` -> `OLDEST_CREATED`。
- `高評価` -> `BEST`。
- `コメント数` -> `MOST_RESPONSED`。

検索仕様は以下です。

- キーワードは半角スペースと全角スペースで分割する。
- すべてのキーワードが含まれる場合のみマッチ。
- スレッド検索はタイトル + 本文を対象にする。
- ログ検索は本文を対象にする。
- マッチ箇所は `<span class="bg-warning">...</span>` でハイライトする。
- 抜粋は最初のマッチ周辺を中心に最大300文字相当。
- ログ検索で子返信がマッチした場合、親ログも表示状態に戻す。

並べ替え仕様は以下です。

- `NEWEST_UPDATED`: `updated_at` 降順。
- `OLDEST_UPDATED`: `updated_at` 昇順。
- `NEWEST_CREATED`: `created_at` 降順。
- `OLDEST_CREATED`: `created_at` 昇順。
- `BEST`: `nLike` 降順。
- `MOST_RESPONSED`: `nRes` 降順。

## 10. Like仕様

旧APIは `good` と `bad` の2種類を持ちます。

- Likeのキーは `post_id + user_id`。
- `post_id` はスレッドIDまたはログID。
- 同じユーザーが同じpostへLikeすると、既存Likeを削除してから新しいLikeを保存する。
- `good` は +1、`bad` は -1 として `n_total = n_good - n_bad`。
- Like作成・削除後は対象スレッドまたはログの `nLike` を再計算する。
- ログIDは `{route}_{ulid}_{ulid}` 形式なので、`post_id` の `_` 個数でスレッド/ログを判定している。

旧Like UIの事実は以下です。

- `arrowUp` と `arrowDown` をimportしているが、描画しているのは上矢印と合計値だけ。
- クリックハンドラとしてはgood/bad双方が実装されている。
- 移行後はAPI互換上 `bad` を必ず維持する。UIは旧表示互換を優先するなら上矢印中心でよいが、機能完成としてはbad操作も明示できる状態が望ましい。

## 11. API仕様

旧APIはChaliceで、全ルートにCORSと `x-api-key` が必要です。認証必須ルートはCognito Authorizerも必要です。移行後も旧フロント互換APIとして同じパス・同じbodyキー・同じレスポンスキーを提供すること。

旧実装では `submission` ではなく `submition` / `submitions` という綴りを使っている。互換APIではこの綴りを維持すること。

| Method | Path | Auth | Request | Response |
| --- | --- | --- | --- | --- |
| GET | `/` | 必須 | なし | `{"message": "...id token payload..."}` |
| GET | `/threads/{route}` | 不要 | なし | `{"submitions": [thread...]}` |
| POST | `/threads/{route}` | 必須 | `{"submition": thread}` | `{"result": true}` or validation errors |
| GET | `/threads/{route}/{thread_id}` | 不要 | なし | `{"thread_info": thread}` |
| PUT | `/threads/{route}/{thread_id}` | 必須 | `{"submition": edited_thread}` | `{"result": true}` or validation errors |
| DELETE | `/threads/{route}/{thread_id}` | 必須 | なし | `{"result": true}` |
| GET | `/bbslogs/{thread_id}` | 不要 | なし | `{"submitions": [log...]}` |
| POST | `/bbslogs/{thread_id}` | 必須 | `{"submition": log}` | `{"result": true}` or validation errors |
| GET | `/bbslogs/{thread_id}/{log_id}` | 不要 | なし | `{"log_info": log}` |
| GET | `/bbslogs/{thread_id}/{log_id}/responses` | 不要 | なし | `{"responses": [log...]}` |
| POST | `/bbslogs/{thread_id}/{log_id}` | 必須 | `{"submition": log}` | `{"result": true}` or validation errors |
| PUT | `/bbslogs/{thread_id}/{log_id}` | 必須 | `{"submition": edited_log}` | `{"result": true}` or validation errors |
| DELETE | `/bbslogs/{thread_id}/{log_id}` | 必須 | なし | `{"result": true}` |
| POST | `/like/own/batch` | 必須 | `{"post_ids": [...]}` | `{"result": true, "likes": [...]}` |
| GET | `/like/{post_id}` | 不要 | なし | `{"likes": {"n_good": n, "n_bad": n, "n_total": n}}` |
| GET | `/like/{post_id}/own` | 必須 | なし | `{"like": like_or_empty}` |
| POST | `/like` | 必須 | `{"post_id": "...", "type": "good|bad", "user_id": "..."}` | `{"result": true}` |
| DELETE | `/like` | 必須 | `{"post_id": "...", "type": "...", "user_id": "..."}` | `{"result": true}` |
| POST | `/user` | 必須 | `{"submition": user}` | `{"result": true}` |
| POST | `/user/signin` | 不要 | `{"submition": {"Username": "...", "v1_password": "..."}}` | `{"result": true, "isV2": bool, "isV1": bool}` |
| POST | `/user/update` | 不要 | `{"submition": {"idToken": "..."}}` | `{"result": true, "user_info": user}` |

新実装で内部APIに `/api` prefix を持ってもよいが、旧互換APIは上記パスで動く必要がある。

## 12. データ仕様

### 12.1 旧テーブル

旧APIはDynamoDBに以下4テーブルを作ります。

| テーブル | キー | LSI | 用途 |
| --- | --- | --- | --- |
| `thread` | `route` HASH, `thread_id` RANGE | `route + updated_at` | スレッド |
| `log` | `thread_id` HASH, `log_id` RANGE | `thread_id + updated_at` | ログ・返信 |
| `like` | `post_id` HASH, `user_id` RANGE | `post_id + type` | Like |
| `user` | `Username` HASH | なし | ユーザー |

テスト時は `_test` suffixのテーブル名を使う。

### 12.2 スレッド項目

旧スレッドの主要属性は以下です。

- `route`: `BBS`, `WIKI`, `DATA`, `IMAGE`
- `thread_id`: `{route}_{ULID}`
- `updated_at`: UTC ISO文字列
- `created_at`: UTC ISO文字列
- `user_id`
- `user_name`
- `title`
- `content`
- `nRes`
- `nLike`
- `filedata`: S3キー配列
- `isEdited`
- `isDeleted`
- v1移行用: `v1_id`, `v1_userID`, `v1_userName`

削除は物理削除ではなく `isDeleted: true` のsoft delete。スレッド削除時は配下ログにも `isDeleted: true` を付ける。

### 12.3 ログ項目

旧ログの主要属性は以下です。

- `thread_id`
- `log_id`: `{thread_id}_{ULID}`
- `response_to`: 返信先ログID。通常ログでは空。
- `updated_at`
- `created_at`
- `user_id`
- `user_name`
- `content`
- `nRes`
- `nLike`
- `isEdited`
- `isDeleted`
- v1移行用: `v1_id`, `v1_resID`, `v1_threadID`, `v1_userID`, `v1_userName`

通常ログ投稿時は親スレッドの `nRes` をインクリメントし、`updated_at` も更新する。ログへの返信投稿時は親スレッドの `nRes` と親ログの `nRes` をインクリメントする。

ログ削除は `isDeleted: true` のsoft delete。旧画面では削除済みログを完全には消さず、`この返信は削除されました` と表示する。

### 12.4 Like項目

旧Likeの主要属性は以下です。

- `post_id`
- `user_id`
- `type`: `good` or `bad`
- `isDeleted`

Like集計は `n_good`, `n_bad`, `n_total` を返す。post本体側には `nLike` として `n_total` を保持する。

### 12.5 ユーザー項目

旧ユーザーの主要属性は以下です。

- `Username`
- `sub`
- `email`
- `email_verified`
- `version`
- v1移行用: `v1_id`, `v1_name`, `v1_password`

旧v1パスワードはSHA-512 hexで比較している。移行時はv1互換ログイン判定を維持し、v1ユーザーにはv2アカウント作成導線を出す。

### 12.6 single-table移行後

移行後の物理テーブルは1つでよい。ただし以下のアクセスパターンを満たすこと。

- routeごとのスレッド一覧を `updated_at` 新しい順で取得。
- `route + thread_id` でスレッド詳細を取得。
- `thread_id` 配下のログ一覧を取得。
- `thread_id + response_to` で返信一覧を取得。
- `post_id` ごとのLike集計を取得。
- `post_id + user_id` で自分のLikeを取得。
- `Username` でユーザーを取得。
- 必要に応じて `sub` と `email` からユーザーを逆引き。

移行インポート時は旧IDを保持する。新規作成は旧ID形式 `{route}_{ULID}` / `{thread_id}_{ULID}` を維持する。

## 13. ファイル仕様

旧ファイル保存はS3 bucket `img.algodooonline.net` に公開readで保存しています。移行後もS3相当のオブジェクト保存を使う。

### 13.1 IMAGE

- クライアントで画像をJPEG Data URLへ変換する。
- APIは `image/jpeg` を受け付ける。
- 保存キーは `IMAGE/{thread_id}_{index}.{extension}`。
- 一覧では最初の画像をサムネイルとして表示する。
- 詳細では全画像をスライドショー表示する。

### 13.2 DATA

- PHZはzipファイルとして扱う。
- PHNはテキストとして扱う。
- PHZ保存キーは `DATA/{thread_id}_{index}.phz`。
- PHN保存キーは `DATA/{thread_id}_{index}.phn`。
- PHZの場合はzip内 `thumb.png` を抽出し、`DATA/{thread_id}_{index}_thumb.png` として保存する。
- 一覧と詳細では `*_thumb.png` をプレビューに使う。
- 詳細では元ファイルへの `ダウンロード` リンクを表示する。

### 13.3 サーバー側検証

旧APIの検証は以下です。

- 許可Content-Typeは `application/zip`, `image/jpeg`, `text/plain`。
- PHZはzipであり、`scene.phn`, `checksums.txt`, `thumb.png` を含む必要がある。
- PHZ内の `scene.phn` と `checksums.txt` はUTF-8またはASCII相当のテキストである必要がある。
- PHZ内のその他ファイルは画像として判定できる必要がある。
- PHNはUTF-8またはASCII相当のテキストである必要がある。
- IMAGEは画像として判定できる必要がある。

## 14. バリデーション仕様

旧フロントのYupバリデーションは以下です。

- スレッド `title`: 必須、最大32文字。
- スレッド `content`: 必須、最大32000文字。
- ログ `content`: 必須、最大32000文字。
- 削除確認 `deletepass`: `削除` または `delete` のみ。
- 認証 `password`: 8文字以上。
- `password_confirm`: `password` と一致。
- `email`: メール形式。
- `name`, `actKey`: 必須。

旧APIのCerberusスキーマ上はログ `content` は1000文字想定、スレッド `title` は32、`content` は32000という意図が見える。ただし旧 `maxLengthString` helper は実際にはmaxlengthを設定していない。移行後はフロント仕様に合わせ、スレッドtitle 32、スレッドcontent 32000、ログcontentは互換性を考えて32000を上限にするのが安全。

## 15. Markdownとセキュリティ

旧Markdown表示は `marked` を使い、独自sanitizerを設定しています。

- Markdownが有効なのは `WIKI`, `IMAGE`, `DATA`。
- `BBS` はMarkdownではない。
- 拒否タグは `script`, `style`, `link`, `iframe`, `embed`, `object`, `html`, `head`, `meta`, `body`, `form`, `input`, `button`。
- 拒否属性は `on*`, `href`, `action`, `id`, `data-*`。
- `<!`, `<?`, `<\` で始まる入力は空にする。

移行後はPython側でMarkdown変換する場合も、上記と同等以上のサニタイズを行う。未サニタイズHTMLをそのまま出してはいけない。

## 16. エラー表示仕様

旧フロントのAPI wrapperは、レスポンス `result` がfalseの場合に `errors` を `Server-side Error` から始まる複数行の文字列に変換し、`.form-error` に赤文字で表示します。

移行後もフォームのサーバー側バリデーションエラーをユーザーに表示すること。API互換では `{"result": false, "errors": {...}}` を維持すること。

## 17. ローカル結合試験条件

Docker Compose 起動後に、ブラウザまたはHTTPテストだけで以下を確認できること。

- `/` が旧ホーム仕様で表示される。
- Navbarに `AlgodooOnline [ver 2.0]`, `サイトマップ`, `ユーザー認証` が表示される。
- `/auth/login` が旧ログイン画面として表示される。
- `/auth/signup`, `/auth/logout`, `/auth/changepass`, `/auth/forgotpass` が旧画面仕様で表示される。
- ローカル代替ログイン後、Navbarが `Hello, {name}!` になる。
- `/i/BBS`, `/i/WIKI`, `/i/IMAGE`, `/i/DATA` が表示できる。
- `/BBS`, `/Wiki`, `/Image`, `/Data` は正規 `/i/...` へリダイレクトされる。
- 未ログイン時、投稿フォームはログイン誘導を出す。
- ログイン時、スレッド作成・編集・削除が画面操作でできる。
- ログイン時、ログ作成・ログ返信・ログ編集・ログ削除が画面操作でできる。
- 削除確認は `削除` または `delete` が必要。
- Like作成・削除・自分のLike取得・集計ができる。
- 検索で本文・タイトルのハイライトと絞り込みができる。
- 並べ替え全パターンが効く。
- `WIKI`, `IMAGE`, `DATA` でMarkdown表示になる。
- `IMAGE` で画像アップロード、一覧サムネイル、詳細スライドショーが確認できる。
- `DATA` でPHZ/PHNアップロード、PHZサムネイル、ダウンロードリンクが確認できる。
- 旧互換APIの全パスが `submition` / `submitions` を含む旧キー名で通る。
- single-tableを使い、通常データ操作で `ddb_single` を迂回していない。

結合テストは `scripts/smoke_local.py` で自動化する。画面仕様を変えた場合は同時にこのテストを更新する。

## 18. 現実装との差分

2026-05-04時点で、`../Algon2-APP` と `../Algon2-API` を再確認した結果、このリポジトリ実装にはまだ以下の残件がある。ここには、すでに修正済みのスレッド一覧Likeクリック領域、ログ返信の入れ子表示、返信ログのLike表示、ログ編集・削除ボタンのメニュー外露出は含めない。

今回確認した旧実装範囲は以下。

- 画面: `../Algon2-APP/src/components/05_Pages/BBSListPage.js`, `../Algon2-APP/src/components/05_Pages/BBSDetailPage.js`
- 掲示板部品: `../Algon2-APP/src/components/02_Molecules/ThreadListItem.js`, `../Algon2-APP/src/components/02_Molecules/ThreadInfoBody.js`, `../Algon2-APP/src/components/02_Molecules/LogItem.js`
- 本文・添付部品: `../Algon2-APP/src/components/01_Atoms/bbs_items/ThreadBody.js`, `LogBody.js`, `MarkdownBody.js`, `DownloadPHZ.js`
- フォーム・モーダル: `../Algon2-APP/src/components/02_Molecules/Forms/ThreadForm.js`, `LogForm.js`, `SearchForm.js`, `DeleteForm.js`, `../Algon2-APP/src/components/01_Atoms/layouts/Modal.js`, `../Algon2-APP/src/components/01_Atoms/parts/Dropzone.js`, `Inputs.js`, `SlideShow.js`
- 旧API: `../Algon2-API/app.py`, `../Algon2-API/chalicelib/post.py`, `schema.py`, `file.py`, `phz.py`

現在残っている差分は以下。これらを解消するまで、移植完了として扱わない。

1. 認証付き旧互換APIの認可が足りない。旧APIは `CognitoUserPoolAuthorizer` と `x-api-key` を要求するが、現実装の `/threads`, `/bbslogs`, `/like`, `/user` 互換APIはCookie未設定でも多くが実行でき、`user_id` もbody由来または `anonymous` になっている。
2. 旧Cognitoセッション更新が未実装。旧フロントは `idToken` 失効前に `refreshToken` で更新し、失敗時だけ未ログインに戻すが、現実装はローカルCookieの有無だけを見ている。
3. ID形式が旧ULIDではない。旧APIは `BBS_01...` のような `ulid.new().str` 形式で `thread_id` / `log_id` を作るが、現実装は `uuid4().hex` を使っている。
4. ファイル投稿の保存処理が旧仕様ではない。旧APIはData URLを検証してS3キー `IMAGE/{thread_id}_{index}...` / `DATA/{thread_id}_{index}...` へ保存し、DBにはファイルキーを残すが、現実装はフォーム値のData URLまたは任意文字列をそのまま `filedata` に保存できる。
5. `IMAGE` 投稿のクライアント処理が旧仕様ではない。旧フロントは `Jimp` で画像をJPEG Data URLへ変換してから送るが、現実装は `FileReader.readAsDataURL` の結果をそのまま入れるだけで、JPEG化も旧API相当のContent-Type制限もない。
6. `DATA` 投稿のPHZ/PHN処理が旧仕様ではない。旧フロントは `JSZip` でPHZ内の `thumb.png` を抽出し、旧APIは `scene.phn`, `checksums.txt`, `thumb.png` と文字コード・画像妥当性を検証するが、現実装はzip検証、PHZサムネイル抽出、PHN文字コード検証をしていない。
7. `DATA` 詳細のダウンロードブロックが旧 `DownloadPHZ` と違う。旧画面は先頭PHZのサムネイルを大きく表示し、黄色枠の `ダウンロード` リンクを `REACT_APP_IMAGE_URL + "/" + filedata[0]` へ張るが、現実装は `filedata` 全件を生のhrefで並べている。
8. `IMAGE` 詳細のスライドショーが旧 `SlideShow` と違う。旧画面は `react-slick` のメイン画像とサムネイルナビ、左右矢印、swipeを持つが、現実装は画像を縦に並べるだけで、サムネイルナビや矢印操作がない。
9. `WIKI` / `IMAGE` / `DATA` の投稿・編集フォームが旧Markdownエディタではない。旧 `ThreadForm` は `SimpleMDE` を使うが、現実装は通常textareaで、EasyMDEのUI、プレビュー、編集体験がない。
10. ログ本文のMarkdown表示が旧仕様と違う。旧 `LogBody` はrouteが `WIKI`, `IMAGE`, `DATA` の場合 `MarkdownBody` でログ本文もMarkdown表示するが、現実装のログ本文は全routeでプレーンテキスト風の `highlight` 表示になっている。
11. Markdown変換とsanitizerが旧仕様に足りない。旧 `MarkdownBody` は `marked` を使い、HTMLタグ・属性を独自sanitizerで制御するが、現実装は見出し、太字、インラインコード程度の簡易regex変換で、旧Markdown互換にも旧sanitizer互換にも達していない。
12. ログ検索で孫以降の返信がマッチした場合の親展開が足りない。旧 `search_logs` は `eneble_response_parent` で祖先を再帰的に `disabled: false` に戻すが、現実装の `list_logs` は直接の親だけを戻すため、孫返信だけが検索にマッチするとルート親まで表示されない可能性がある。
13. ログ一覧の初期並びが旧画面と違う。旧 `getLogs` は取得後に `NEWEST_UPDATED` で並べるが、現実装の `list_logs` はsort未指定時に `NEWEST_CREATED` を既定にしている。
14. サーバー側バリデーションエラーの形と表示が旧仕様と違う。旧APIはCerberusの `errors` を返し、旧フロントは `Server-side Error` から始まる複数行文字列として `.form-error` に出すが、現実装はエラー値が文字列で、サーバーレンダリングフォーム側も失敗理由を同じ形で表示しない。
15. ユーザー移行用属性が不足している。旧 `UserSchema` は `v1_id`, `v1_name`, `v1_password` を持つが、現実装の `UserProfile` / `UserRecord` は主に `v1_password` だけで、v1ユーザー情報の保持範囲が旧仕様より狭い。

上記残件は、画面見た目だけでなく旧サービスの操作結果、保存データ、API互換、添付ファイルの扱いに直結するため、個別に旧実装を参照して修正し、対応する `scripts/smoke_local.py` の確認項目を追加すること。

補足として、旧互換の `GET /`（`message` にトークン相当の情報を載せる）は、ブラウザ向け HTML の `GET /` と衝突しないよう、`Accept` の先頭メディアタイプが `application/json` のときだけ JSON を返し、未認証なら 401 とする。スレッド詳細の返信一覧は、旧画面のログイン時のみ取得に合わせ、未ログインの画面では返信一覧を出さない。

**実装進捗（2026-05-05）**: 旧互換 JSON API について `LEGACY_X_API_KEY` 設定時の `x-api-key` 検証、ミューテーション系でのセッション Cookie 必須と `user_id` の一致、`thread_id`/`log_id` の ULID 化、ログ一覧の既定ソートを `NEWEST_UPDATED` へ、ログ検索時の祖先ログ再帰含有、`WIKI`/`IMAGE`/`DATA` のログ本文 Markdown 化（簡易 sanitizer 付き）、`IMAGE` の JPEG Data URL 検証、`UserProfile` の `v1_id`/`v1_name` 保持を追加した。未着手または部分対応が残るのは Cognito 相当のトークン更新、S3 実保存と PHZ 完全検証、スライドショー/SimpleMDE 級 UI、サーバーレンダリングフォームの `.form-error` 複数行整形、旧エディタ相当の Markdown 互換の網羅などである。
