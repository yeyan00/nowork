const fs = require('fs');
const path = require('path');

const zhPath = path.join(__dirname, '..', 'web/src/i18n/zh-CN.json');
const data = JSON.parse(fs.readFileSync(zhPath, 'utf8'));

data.filePreview = {
  files: '\u6587\u4ef6',
  closeSidebar: '\u5173\u95ed\u4fa7\u8fb9\u680f',
  selectWorkspace: '\u9009\u62e9\u5de5\u4f5c\u533a',
  noWorkspaces: '\u65e0\u5de5\u4f5c\u533a',
  searchFiles: '\u641c\u7d22\u6587\u4ef6...',
  refresh: '\u5237\u65b0',
  loading: '\u52a0\u8f7d\u4e2d...',
  noResults: '\u65e0\u7ed3\u679c',
  selectToPreview: '\u9009\u62e9\u6587\u4ef6\u4ee5\u9884\u89c8',
  clickFileHint: '\u70b9\u51fb\u6587\u4ef6\u6811\u4e2d\u7684\u6587\u4ef6\u6216\u804a\u5929\u4e2d\u7684\u6587\u4ef6\u5361\u7247',
  preview: '\u9884\u89c8',
  switchToEdit: '\u7f16\u8f91',
  switchToPreview: '\u9884\u89c8',
  fromMessage: '\u6765\u81ea\u804a\u5929\u6d88\u606f',
  fileTree: '\u6587\u4ef6\u6811',
  collapseTree: '\u6536\u8d77\u6587\u4ef6\u6811',
  expandTree: '\u5c55\u5f00\u6587\u4ef6\u6811'
};
data.chat.toggleFilePreview = '\u6587\u4ef6';
data.chat.showFilePreview = '\u663e\u793a\u6587\u4ef6';
data.chat.hideFilePreview = '\u9690\u85cf\u6587\u4ef6';

fs.writeFileSync(zhPath, JSON.stringify(data, null, 2), 'utf8');
console.log('zh-CN.json updated');
