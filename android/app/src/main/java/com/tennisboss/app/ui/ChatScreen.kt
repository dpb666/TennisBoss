package com.tennisboss.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ChatMessage

@Composable
fun ChatScreen(vm: ChatViewModel = viewModel()) {
    val context = LocalContext.current
    val listState = rememberLazyListState()
    var input by remember { mutableStateOf("") }

    val filePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        uri?.let { vm.uploadFile(context, it, "Analyse ce fichier et résume les informations clés") }
    }

    // Scroll automatique au dernier message
    LaunchedEffect(vm.messages.size) {
        if (vm.messages.isNotEmpty()) {
            listState.animateScrollToItem(vm.messages.size - 1)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .imePadding(),
    ) {
        // En-tête
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("🤖", fontSize = 22.sp)
                Text(
                    "  TennisBoss AI",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            if (vm.messages.isNotEmpty()) {
                TextButton(onClick = { vm.clear() }) {
                    Text("Effacer", style = MaterialTheme.typography.labelSmall)
                }
            }
        }

        // Bulle d'accueil si vide
        if (vm.messages.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("🎾", fontSize = 48.sp)
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "Pose moi n'importe quelle question sur le tennis :\ncomparaisons de joueurs, surfaces, ELO, valeur des cotes…",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 8.dp),
                    )
                    Spacer(Modifier.height(20.dp))
                    SuggestionChips(onSelect = { vm.send(it) })
                }
            }
        } else {
            // Liste des messages
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).testTag("chat_messages"),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(vm.messages) { msg ->
                    MessageBubble(msg)
                }
                if (vm.loading) {
                    item { TypingIndicator() }
                }
            }
        }

        // Barre de saisie
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Bouton upload fichier
            IconButton(
                onClick = { filePicker.launch("*/*") },
                enabled = !vm.loading,
                modifier = Modifier
                    .testTag("chat_upload")
                    .semantics { contentDescription = "Joindre un fichier" },
            ) {
                Text("📎", fontSize = 20.sp)
            }
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                modifier = Modifier.weight(1f).testTag("chat_input"),
                placeholder = { Text("Ex : Sinner vs Alcaraz sur terre ?") },
                shape = RoundedCornerShape(24.dp),
                singleLine = false,
                maxLines = 3,
                keyboardOptions = KeyboardOptions(
                    capitalization = KeyboardCapitalization.Sentences,
                    imeAction = ImeAction.Send,
                ),
                keyboardActions = KeyboardActions(onSend = {
                    if (input.isNotBlank()) { vm.send(input); input = "" }
                }),
            )
            Spacer(Modifier.size(8.dp))
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .background(
                        if (input.isNotBlank() && !vm.loading)
                            MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant,
                        CircleShape,
                    ),
                contentAlignment = Alignment.Center,
            ) {
                if (vm.loading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(22.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                } else {
                    IconButton(
                        onClick = { if (input.isNotBlank()) { vm.send(input); input = "" } },
                        enabled = input.isNotBlank(),
                        modifier = Modifier
                            .testTag("chat_send")
                            .semantics { contentDescription = "Envoyer" },
                    ) {
                        Text("➤", fontSize = 18.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun MessageBubble(msg: ChatMessage) {
    val isUser = msg.role == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        if (!isUser) {
            Text("🤖", fontSize = 18.sp, modifier = Modifier.padding(end = 6.dp, top = 4.dp))
        }
        Surface(
            shape = RoundedCornerShape(
                topStart = if (isUser) 16.dp else 4.dp,
                topEnd = if (isUser) 4.dp else 16.dp,
                bottomStart = 16.dp,
                bottomEnd = 16.dp,
            ),
            color = if (isUser)
                MaterialTheme.colorScheme.primary
            else
                MaterialTheme.colorScheme.surfaceVariant,
            modifier = Modifier.widthIn(max = 300.dp),
        ) {
            Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                Text(
                    text = msg.content,
                    color = if (isUser)
                        MaterialTheme.colorScheme.onPrimary
                    else
                        MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (msg.context_used) {
                    Text(
                        "📊 Basé sur nos données (ELO, forme, H2H)",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun TypingIndicator() {
    Row(
        modifier = Modifier.padding(start = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("🤖", fontSize = 18.sp, modifier = Modifier.padding(end = 6.dp))
        Surface(
            shape = RoundedCornerShape(topStart = 4.dp, topEnd = 16.dp, bottomStart = 16.dp, bottomEnd = 16.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                repeat(3) {
                    Box(
                        modifier = Modifier
                            .size(7.dp)
                            .background(
                                MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                CircleShape,
                            )
                    )
                }
            }
        }
    }
}

@Composable
private fun SuggestionChips(onSelect: (String) -> Unit) {
    data class Chip(val label: String, val query: String)
    val chips = listOf(
        Chip("📊 Stats match",    "@stats_agent Sinner vs Alcaraz"),
        Chip("💎 Value bets",     "@odds_agent meilleurs value bets du moment"),
        Chip("🔬 Analyse",        "@analyzer_agent Djokovic vs Sinner sur terre"),
        Chip("🎾 Top ELO",        "Quels sont les meilleurs joueurs ELO en ce moment ?"),
        Chip("🏟 Surface",        "Qui domine sur gazon cette saison ?"),
        Chip("📈 Forme récente",  "Compare la forme de Alcaraz et Zverev"),
    )
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        chips.forEach { chip ->
            Surface(
                onClick = { onSelect(chip.query) },
                shape = RoundedCornerShape(20.dp),
                color = MaterialTheme.colorScheme.surfaceVariant,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    chip.label,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
