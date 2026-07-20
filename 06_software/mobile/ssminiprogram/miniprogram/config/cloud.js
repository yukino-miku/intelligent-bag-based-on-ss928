const defaults = require("./cloud.example");

let local = {};
try {
  local = require("./cloud.local");
} catch (error) {
  local = {};
}

module.exports = Object.assign({}, defaults, local);
