import antlr3
import re

from antlr3.tree import CommonTree

from typing import Dict, List

from Monitor.ClassDebug import Debug
from Monitor.ProtoCCTable import ProtoCCTablePrinter

from Parser.ProtoCCLexer import ProtoCCLexer
from Parser.ProtoCCParser import ProtoCCParser
from Parser.ProtoCCcomTreeFct import *
from Parser.CopyReducedCommonTree import copy_tree

from DataObjects.ClassProtoCCObject import PCCObject
from DataObjects.ClassStateNode import StateNode
from DataObjects.ClassTransition import Transition
from DataObjects.ClassTransaction import Transaction
from DataObjects.ClassMessage import Message

from Graphv.ProtoCCGraph import ProtoCCGraph


class ProtoParser(Debug):

    # PARSER TOKENS ####################################################################################################
    Objects = {
        'CONSTANT_': '_CreateConstant',
        'NETWORK_': '_CreateNetwork',
        'CACHE_': '_CreateCache',
        'DIR_': '_CreateDir',
        'MEM_': '_CreateMem',
        'MSG_': '_CreateMsgObj',
        'ARCH_': '_CreateArch',
    }

    ArchEntity = {
        'MACHN_': '_CheckMachine',
        'PROC_': '_CreateProc',
        'STABLE_': '_CreateStableSet',
    }

    TransEntity = {
        'TRANS_': '_CreateTrans',
        'ASSIGN_': '_CreateAssign',
        'SEND_': '_SendMsg',
        'MCAST_': '_SendMsg',
        'BCAST_': '_SendMsg',
        'AWAIT_': '_TransactionFork',
        'WHEN_': '_NewTransition',
        'ENDWHEN_': '_EndTransition',
        'GUARD_': '_SetTransGuard',
        'ENDPROC_': '_EndProcess',
        'BREAK_': '_EndTransaction',
        'IFELSE_': '_CreateIfElse',
        'IF_': '_NewIfElseFork',
        'ENDIF_': '_HandleEndif',
        'COND_': '_HandleCond',
        'NCOND_': '_HandleCond',
        'SETFUNC_': '_SetFunctions',
        'MODSTATEFUNC_': '_mod_state_func'
    }

    AssignObj = {
        'MSGCSTR_': '_CreateMsg',
        'SETFUNC_': '_SetFunctions',
    }

    # Access keywords
    Access = ['load', 'acquire', 'store', 'release', 'fence']
    Evict = ['evict']
    Accesses = Access + Evict

    # Keywords
    Data = 'DATA_'
    State = 'State'

    def __init__(self, file="", filename="", graphexport=False, dbg_enabled: bool = False):
        Debug.__init__(self, dbg_enabled)

        # PROTO DATA OBJECTS ####
        self.constNode: Dict[str, CommonTree] = {}
        self.networkNode: List[CommonTree] = []

        # Architecture nodes
        self.cache_node: PCCObject = None
        self.dir_node: PCCObject = None
        self.mem_node: PCCObject = None

        self.msgNode: List[PCCObject] = []
        self.msgTypes: List[str] = []
        self.dataMsgTypes: List[str] = []  # Data msg type names, should be included in the message

        self.archNode: Dict[str, List[Transaction]] = {}
        self.stableStates: Dict[str, List[str]] = {}        # [arch_name, List[stable_state_names]
        self.initStateNodes: Dict[str, str] = {}                # This is missing

        if file and filename:
            self.filename = filename
            lexer = ProtoCCLexer(antlr3.StringStream(file))
            parser = ProtoCCParser(antlr3.CommonTokenStream(lexer))
            tree = parser.document().getTree()
            new_tree_base = copy_tree(tree)
            self.pdebug(new_tree_base.toStringTree())
            self._ParseNodes(new_tree_base)

            self.perror("Accesses for SSP not defined", self.checkAccessBehaviourDefined())
            self.perror("Terminal states detected in SSP", self.checkAllStatesReachable())

            if graphexport:
                self._dArch()


########################################################################################################################
# PUBLIC FUNCTIONS
########################################################################################################################

    def checkAccessBehaviourDefined(self):
        # Ensure SSP specifies behaviour for every access in every stable state
        cache = self.cache_node
        for stable_state in self.getStableStates().get(cache):
            access_found_dict = {access: False for access in self.Accesses}
            if not self._hasDataPermission(cache, stable_state):
                # Don't expect evictions if don't have any permission
                access_found_dict['evict'] = True
            for trans in self.getArchitectures().get(cache):
                if (trans.getstartstate().getstatename() == stable_state
                        and trans.getaccess() != ''):
                    access_found_dict[trans.getaccess()] = True
            for access, found in access_found_dict.items():
                if not found:
                    self.pwarning("No behaviour for an access of type \"" + access
                                  + "\" modelled for (cache) stable state \""
                                  + stable_state + "\" in the input SSP.")
                    return True
        # Have checked every stable state without finding any faults
        return True

    def checkAllStatesReachable(self) -> bool:
        ret = True
        ret = ret and self.checkAllStatesReachableArchs(self.cache_node)
        ret = ret and self.checkAllStatesReachableArchs(self.dir_node)
        ret = ret and self.checkAllStatesReachableArchs(self.mem_node)

        return ret

    def checkAllStatesReachableArchs(self, node: PCCObject) -> bool:
        # First loop over all caches and check for their state reachability
        start_state_name = None

        for key, val in node.getvariables().items():
            if val == "INITSTATE_":
                start_state_name = key
                self.initStateNodes[str(node)] = key
                break

        if not start_state_name:
            self.pwarning("Unable to locate the name of the initial state of " + "\"" + node + "\".")
            return False

        # Explore the state space via depth-first search
        if not self._dfsExplore(node, start_state_name):
            return False

        # If not return false yet must have found that all states are reachable
        return True

    def getArchitectures(self) -> Dict[str, List[Transition]]:
        archtrans = {}
        for arch in self.archNode:
            archtrans.update({arch: self._extractTransitions(self.archNode[arch])})
        return archtrans

    def _extractTransitions(self, transactions) -> List[Transition]:
        transitions = []
        for transaction in transactions:
            transitions += transaction.gettransitions()

        transitions = self._filterTransitions(transitions)

        return transitions

    def getConstants(self):
        return self.constNode

    def getNetwork(self):
        return self.networkNode

    def getMessages(self):
        return self.msgTypes

    def getMessageNodes(self):
        return self.msgNode

    def get_mach_nodes(self):
        return {**self.cache_node, **self.dir_node, **self.mem_node}

    def getCacheIdentifiers(self):
        return str(self.cache_node)

    def getDirIdentifiers(self):
        return str(self.dir_node)

    def getMemIdentifiers(self):
        return str(self.mem_node)

    def getAccess(self):
        return self.Access

    def getEvict(self):
        return self.Evict

    def getStableStates(self):
        return self.stableStates

    def getInitStates(self):
        return self.initStateNodes

    def getDataMsgTypes(self):
        return self.dataMsgTypes

    def getFilename(self):
        return self.filename

########################################################################################################################
# PARSER ENTRY POINT
########################################################################################################################

    def _ParseNodes(self, tree):
        objects = tree.getChildren()
        for obj in objects:
            method_fct = self.Objects[obj.getText()]
            method = getattr(self, method_fct, lambda: '__UnknownNode__')
            method(obj)

        self._pArchTable()

    def _UnknownNode(self, obj):
        self.perror("Unknown Node Identifier")
        self.perror(obj.getText())

########################################################################################################################
# SECTIONS
########################################################################################################################

    def _CreateConstant(self, obj: CommonTree):
        data = obj.getChildren()
        self.constNode[str(data[0])] = str(data[1])

    def _CreateNetwork(self, obj: CommonTree):
        self.networkNode.append(obj)

    def _CreateCache(self, obj: CommonTree):
        assert not self.cache_node, "A cache has already been defined at this level"
        self.cache_node = self._createObj(obj)

    def _CreateDir(self, obj: CommonTree):
        assert not self.dir_node, "A directory has already been defined for this level"
        self.dir_node = self._createObj(obj)

    def _CreateMem(self, obj: CommonTree):
        assert not self.mem_node, "A memory has already been defined for this level"
        self.mem_node = self._createObj(obj)

    def _CreateMsgObj(self, obj: CommonTree):
        self.msgNode.append(PCCObject(obj))

        msgformat = obj.getChildren()

        msgtype = ""
        for ind in range(0, len(msgformat)):
            if ind == 0:
                msgtype = msgformat[ind].getText()
            else:
                if msgformat[ind].getText() == self.Data:
                    self.dataMsgTypes.append(msgtype)

    def _CreateArch(self, arch):
        machname = ''
        transactions = []
        stablestates = []

        for comp in arch.getChildren():
            method_fct = self.ArchEntity[comp.getText()]
            method = getattr(self, method_fct, lambda: '__UnknownNode__')
            result = method(comp)

            if isinstance(result, str):
                machname = result
            elif isinstance(result, Transaction):
                transactions.append(result)
            elif isinstance(result, list):
                stablestates += result
            else:
                self.perror("Unexpected data type")

        self.archNode.update({machname: transactions})
        self.stableStates.update({machname: stablestates})

        self.pdebug("Architecture " + machname + ", #Transactions: " + str(len(transactions)))

########################################################################################################################
# OBJECT METHODS
########################################################################################################################

    @staticmethod
    def _getName(obj):
        return obj.getText()

    def _getObjName(self, child):
        return {self._getName(child.getChild(0)): child.getChild(0)}

    def _createObj(self, obj):
        return {self._getName(obj.getChild(0)): PCCObject(obj)}

########################################################################################################################
# ARCHITECTURE
########################################################################################################################

    def _CheckMachine(self, comp):
        # Make sanity check if Object for architecture exists
        machname = comp.getChildren()

        if len(machname) > 1:
            self.perror("Machine name error" + str(machname))

        refcache = list(filter(lambda x: machname[0].getText() == x.getname(),
                               (list(self.cache_node) +
                                list(self.dir_node) +
                                list(self.mem_node))))

        if len(refcache) == 0:
            self.perror("The machine was not defined: " + str(machname[0].getText()), refcache)

        elif len(refcache) > 1:
            self.perror("Machine names are ambigous " + refcache[0].getname())

        else:
            refcache = refcache[0]

        if not refcache:
            self.perror("Architecture " + refcache.GetName() + " does not exist as Machine")

        return machname[0].getText()

    @staticmethod
    def _CreateStableSet(stable):
        stablenodes = stable.getChildren()

        stablestates = []
        for node in stablenodes:
            stablestates.append(node.getText())

        return stablestates

    def _CreateProc(self, architecture, transaction: Transaction = 0):

        for comp in architecture.getChildren():
            try:
                method_fct = self.TransEntity[comp.getText()]
            except KeyError:
                assert 0, "Unknown Token"
            method = getattr(self, method_fct, lambda: '__UnknownNode__')
            transaction = method(comp, transaction)

        return transaction

    def _EndProcess(self, comp=0, transaction: Transaction = 0):
        nrinit = transaction.getnrtransitions()
        endnodes = transaction.endifconstr()
        if endnodes:
            for node in endnodes:
                curtrans = node.getdata()
                if curtrans.getfinalstate().getstatename() == transaction.getinterfinalstate():
                    curtrans.getfinalstate().setstatename(curtrans.getstartstate().getstatename())
        else:
            curtrans = transaction.getcurtransition()
            if curtrans.getfinalstate().getstatename() == transaction.getinterfinalstate() \
                    and curtrans.getfinalstate().getstatename() == self.State:
                    curtrans.getfinalstate().setstatename(curtrans.getstartstate().getstatename())

        transaction.pushtransition()
        self.pdebug("New transitions due to fork: " + str(transaction.getnrtransitions() - nrinit))

        return transaction

    def _CreateTrans(self, trans, transaction: Transaction):
        if not isinstance(transaction, int):
            self.perror("Nested transactions are not permitted")

        transsetup = toStringList(trans)

        # Static format
        startstate = StateNode(transsetup[1], self.Accesses)

        if len(transsetup) > 3:
            finalstate = StateNode(transsetup[3], self.Accesses)
        else:
            finalstate = StateNode(self.State, self.Accesses)

        transaction = Transaction(startstate, transsetup[2], finalstate)

        return transaction


########################################################################################################################
# AWAIT (WHEN GUARD)+
########################################################################################################################

    def _TransactionFork(self, node, transaction: Transaction = 0):
        transaction.endifconstr()
        curtrans = transaction.getcurtransition()
        if curtrans.getfinalstate().getstatename() == transaction.getinterfinalstate():
            # Generate new intermediate state name
            finalstate = curtrans.getstartstate().getstatename() + "_" + curtrans.getguard()
            curtrans.getfinalstate().setstatename(finalstate)
            self.pdebug(transaction.getcurtransition().pbase())

        self._CreateProc(node, transaction)
        return transaction

    def _NewTransition(self, node, transaction: Transaction = 0):
        transaction = self._CreateProc(node, transaction)
        return transaction

    def _SetTransGuard(self, node, transaction: Transaction = 0):
        guardtype = node.getChild(0).toString()
        guardmsg = Message(guardtype)

        if not list(filter(lambda x: guardtype == x, self.msgTypes)):
            self.msgTypes.append(guardtype)

        # Append new transition to tree (When is always succeded by a guard
        prenode = transaction.getcurtransitionode()
        startstate = transaction.getcurtransition().getfinalstate()
        finalstate = StateNode(transaction.getinterfinalstate(), self.Accesses)
        transaction.newwhen(startstate, finalstate, guardmsg, prenode)

        return transaction

    def _EndTransition(self, node=0, transaction: Transaction = 0):
        endnodes = transaction.endifconstr()

        # Check if the final state has changed from default
        # If not loop in intermediate state
        if not endnodes:
            transition = [transaction.getcurtransition()]
        else:
            transition = []
            for entry in endnodes:
                transition.append(entry.getdata())

        for curtrans in transition:
            if curtrans.getfinalstate().getstatename() == transaction.getinterfinalstate():
                curtrans.getfinalstate().setstatename(curtrans.getstartstate().getstatename())

        # return to preceeding tree node
        assert not transaction.getcurtransitionode() == transaction.endwhen(), "Unexpected behaviour"

        return transaction

    def _EndTransaction(self, node=0, transaction: Transaction = 0):
        # Check if the final state has changed from default
        # If not return to start state
        curtrans = transaction.getcurtransition()
        if curtrans.getfinalstate().getstatename() == transaction.getinterfinalstate():
            curtrans.setfinalstate(transaction.getstartstate())
        return transaction

########################################################################################################################
# ASSIGNMENT
########################################################################################################################

    @staticmethod
    def _AssignVarName(assign):
        return ''.join(toStringList((assign.getChildren())[0]))

    def _CreateAssign(self, assign, transaction: Transaction):

        transaction.addoperation(assign)

        # Assign new variable name
        # [left op assign]
        assigndef = assign.getChildren()

        # Check for object initialization
        for comp in assigndef:
            if comp.getChildren():
                if not list(filter(lambda x: comp.getText() == x, self.msgTypes)):
                    try:
                        method_fct = self.AssignObj[comp.getText()]
                    except KeyError:
                        method_fct = 0

                    if method_fct:
                        method = getattr(self, method_fct, lambda: '__UnknownNode__')
                        transaction = method(comp, transaction)

        # Set state name
        if assigndef[0].toString() == transaction.getinterfinalstate():
            transaction.setfinalstate(assigndef[2].toString())
            self.pdebug(transaction.getcurtransition().pbase())

        return transaction

    ####################################################################################################################
    # Message assignment
    ####################################################################################################################

    def _CreateMsg(self, message, transaction: Transaction):
        # msg: format
        # [object, type, src, dest, payload..]

        varname = self._AssignVarName(message.getParent())

        msg = message.getChildren()
        msgobj = msg[0].getText()

        if not list(filter(lambda x: msgobj in x.getname(), self.msgNode)):
            self.perror("Object related to constructor undefined")

        if msg[1].getChildren():
            self.perror("Expected message identifier")

        msgtype = msg[1].getText()
        msgsrc = ''.join(toStringList(msg[2]))
        msgdest = ''.join(toStringList(msg[3]))

        payload = []
        for ind in range(4, len(msg)):
            payload.append(''.join(toStringList(msg[ind])))

        msgconstr = Message(msgtype, msgobj, msgsrc, msgdest, payload, msgobj)
        transaction.addmessage(varname, msgconstr)

        if not list(filter(lambda x: msgtype == x, self.msgTypes)):
            self.msgTypes.append(msgtype)

        return transaction

########################################################################################################################
# NETWORK FUNCTIONs
########################################################################################################################

    def _SendMsg(self, message, transaction: Transaction):
        transaction.addoperation(message)

        send = toStringList(message)
        msg = transaction.getmessage(send[2])
        msg.setvc(send[1])
        transaction.addoutmsg(msg)

        return transaction

########################################################################################################################
# IF ELSE
########################################################################################################################

    def _CreateIfElse(self, node, transaction: Transaction):
        transaction.newifconstr()
        self._CreateProc(node, transaction)
        return transaction

    def _NewIfElseFork(self, node, transaction: Transaction):
        transaction.newifelse()
        self._CreateProc(node, transaction)
        return transaction

    @staticmethod
    def _HandleCond(node, transaction: Transaction):
        transaction.getcurtransition().addoperation(node)
        transaction.getcurtransition().addcond(''.join(toStringList(node)))
        return transaction

    @staticmethod
    def _HandleEndif(node=0, transaction: Transaction = 0):
        transaction.endif()
        return transaction

########################################################################################################################
# SET FUNCTION
########################################################################################################################
    @staticmethod
    def _SetFunctions(node, transaction: Transaction):
        transaction.addoperation(node)
        return transaction

    @ staticmethod
    def _mod_state_func(node, transaction: Transaction):
        transaction.addoperation(node)
        return transaction

########################################################################################################################
# POST-PROCESSING
########################################################################################################################
    def _filterTransitions(self, transitions):
        guardtransmap = {}
        for transition in transitions:
            guard = transition.getstartstate().getstatename() + transition.getguard() + "".join(transition.getcond())

            if guard in guardtransmap:
                entryset = set([self._stripstr(op.toStringTree()) for op in guardtransmap[guard].getoperation()])
                transset = set([self._stripstr(op.toStringTree()) for op in transition.getoperation()])

                if transset.issuperset(entryset):
                    guardtransmap.update({guard: transition})
                else:
                    if not entryset.issuperset(transset):
                        self.perror("In State: " + transition.getstartstate().getstatename()
                                    + "; At guard " + transition.getguard()
                                    + "; multiple inconsistent behavioural descriptions exist for condition:"
                                    + " ".join(transition.getcond()))

            else:
                guardtransmap.update({guard: transition})

        return list(guardtransmap.values())

    def _stripstr(self, string):
        return re.sub(r'\W', '', string)

########################################################################################################################
# DEBUG
########################################################################################################################

    def _dArch(self):
        for arch in self.archNode:
            transactions = self.archNode[arch]
            transitions = []
            for transaction in transactions:
                transitions += transaction.gettransitions()

            transitions = self._filterTransitions(transitions)

            ProtoCCGraph("SSP_Spec: " + arch, transitions)

    def _pArchTable(self):
        for arch in self.archNode:
            transitions = []
            for transaction in self.archNode[arch]:
                transitions += transaction.gettransitions()

            transitions = self._filterTransitions(transitions)

            ProtoCCTablePrinter().ptransitiontable(transitions)

    def _pArch(self):
        for arch in self.archNode:
            self._pArchTransactions(arch, self.archNode[arch])
            self._pArchTransitions(arch, self.archNode[arch])

    def _pArchTransactions(self, name, transactions):
        pheader(name + " :Transactions Summary")
        ProtoCCTablePrinter().ptransactions(transactions)

    def _pArchTransitions(self, name, transactions):
        pheader(name + " :Transitions Summary")
        ProtoCCTablePrinter().ptransaction(transactions)

    def _pMessages(self):
        pheader("\nMessages")
        for entry in self.msgTypes:
            pdebug(entry)
        pdebug('\n')

    ################################################################################
    # MISC
    ################################################################################
    def _dfsExplore(self, arch, start_state_name):
        # Build up a graph of the transitions for the architecture
        # (X : {A, B, ..} -> there are transitions
        # from X to A, B, ...)
        transition_graph = {}
        for trans in self.getArchitectures().get(arch):
            trans_state_name = trans.getstartstate().getstatename()
            if trans_state_name in transition_graph:
                transition_graph[trans_state_name].add(
                    trans.getfinalstate().getstatename())
            else:
                transition_graph[trans_state_name] = {
                    trans.getfinalstate().getstatename()}

        # Keep track of which states have been visited
        visited_map = set()

        # Explore transition graph via DFS, adding to the visited map
        # as we go
        self._dfsExploreFromVertex(
            start_state_name, transition_graph, visited_map)

        # Make sure all stable states are reachable from the initial state
        for state_name in self.getStableStates().get(arch):
            if state_name not in visited_map:
                self.pwarning('State \"' + state_name + '\" of architecture \"'
                              + arch + '\" is not reachable from the initial '
                              + 'state as it has been defined in the input .pcc'
                              + ' file.')
                return False

        # Have now checked all specified architectures without finding any
        # "lost" states
        return True

    def _dfsExploreFromVertex(self, start_state_name, transition_graph, visited_map):
        # do nothing if we've already explored this node
        if start_state_name not in visited_map:
            visited_map.add(start_state_name)

            for state_name in transition_graph.get(start_state_name) or []:
                # (the 'or []' here ensures Python doesn't throw an error if
                # transition_graph.get(start_state_name) is None, but instead
                # just does nothing)
                self._dfsExploreFromVertex(state_name, transition_graph, visited_map)

    def _hasDataPermission(self, arch, state_name):
        """ Check if architecture arch has any data permissions (load or
            store) in state state_name. """
        for trans in self.getArchitectures().get(arch):
            if (trans.getstartstate().getstatename() == trans.getfinalstate().getstatename()
                    and trans.getstartstate().getstatename() == state_name
                    and trans.getaccess() != ''):
                return True
        return False

