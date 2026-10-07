import { addEventListener, definePlugin, removeEventListener } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaPowerOff } from "react-icons/fa";

import { DISPATCHED_EVENT, type DispatchRecord } from "./api";
import { Panel } from "./components/Panel";
import { emitDispatched } from "./events";
import { toastDispatchEvent } from "./notify";
import { cancelPendingChecks } from "./store";
import { PLUGIN_NAME } from "./strings";

export default definePlugin(() => {
  // One listener for the plugin's lifetime: toast (manual wakes from this panel
  // toast themselves) and fan out to whatever panel is mounted.
  const onDispatched = (record: DispatchRecord) => {
    toastDispatchEvent(record);
    emitDispatched(record);
  };
  addEventListener<[DispatchRecord]>(DISPATCHED_EVENT, onDispatched);

  return {
    name: PLUGIN_NAME,
    titleView: <div className={staticClasses.Title}>{PLUGIN_NAME}</div>,
    content: <Panel />,
    icon: <FaPowerOff />,
    onDismount() {
      removeEventListener(DISPATCHED_EVENT, onDispatched);
      cancelPendingChecks();
    },
  };
});
