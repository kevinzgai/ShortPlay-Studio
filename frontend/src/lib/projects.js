/* =========================================================================
 * 项目管理 API（服务端 projects/ 目录）
 * 项目是唯一真源：刷新、重开浏览器、换标签页都从磁盘读回来。
 * 浏览器本地只留一份「缓存 + 上次打开的项目 id」，服务不可用时兜底。
 * ========================================================================= */

function url(p) { return "/api/" + p; }

function parse(r) {
  return r.json().then(function (j) {
    if (!r.ok) throw new Error((j && j.detail) || ("接口返回 " + r.status));
    return j;
  });
}

function getJSON(p) {
  return fetch(url(p), { cache: "no-store" }).then(parse);
}

function postJSON(p, body, opts) {
  var init = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  };
  if (opts && opts.keepalive) init.keepalive = true;
  return fetch(url(p), init).then(parse);
}

/** 列表只回摘要（不含项目正文），项目多了也不会拖慢首屏。 */
function list() { return getJSON("projects"); }

/** 整份项目（含 data） */
function get(id) { return getJSON("projects/get?id=" + encodeURIComponent(id)); }

function create(name, data) { return postJSON("projects/create", { name: name, data: data }); }

function save(id, name, data, opts) {
  return postJSON("projects/save", { id: id, name: name, data: data }, opts);
}

function rename(id, name) { return postJSON("projects/rename", { id: id, name: name }); }

function remove(id) { return postJSON("projects/delete", { id: id }); }

function duplicate(id) { return postJSON("projects/duplicate", { id: id }); }

/** 关页前的最后一次落盘：sendBeacon 不保证返回，失败由下次自动保存补上。 */
function beaconSave(id, name, data) {
  try {
    var body = JSON.stringify({ id: id, name: name, data: data });
    if (navigator.sendBeacon) {
      return navigator.sendBeacon(url("projects/save"),
        new Blob([body], { type: "application/json" }));
    }
    return fetch(url("projects/save"), {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "application/json" }, body: body
    }).then(function () { return true; }).catch(function () { return false; });
  } catch (e) { return false; }
}

export default { list: list, get: get, create: create, save: save,
  rename: rename, remove: remove, duplicate: duplicate, beaconSave: beaconSave };
