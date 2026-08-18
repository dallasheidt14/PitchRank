// Unset, react-dom logs "environment is not configured to support act(...)" on every
// acted update and never warns about un-acted ones. Both diagnostics key off this global.
declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

export {};
