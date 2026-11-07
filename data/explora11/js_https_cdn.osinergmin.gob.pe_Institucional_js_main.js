$(document).ready(function(){

		 var varSetIntervalxegg=setInterval(function() {
                                                  
         if($("#desplegable-doc").length)
         {
          $('div[id ="desplegable-doc"]').each(function()
          {
     $(this).find('.accordion-toggle').click(function(){
     $(this).addClass('activo').next().addClass('ocultar').show('fast');
     });
     
     $(this).find('.close').click(function(){
     $(this).removeClass('ocultar').parent().hide().parent().parent().find('h4').removeClass('activo');
     });
    //clearInterval(varSetIntervalxegg);
    });
    
         }
     },100);

			

	$(".menuv_osinergmin [href]").each(function() {
	var UrlActual=window.location.href.toUpperCase();
	var UrlMenu=this.href.toUpperCase();
    if (UrlMenu == UrlActual || (UrlMenu  + '/' == UrlActual) || (UrlActual.indexOf(UrlMenu  + '#') > -1 ) || (UrlActual.indexOf(UrlMenu  + '/#') > -1) ) {
   		$('.menuv_osinergmin ul').addClass('close_ul').parent('li').addClass('arrowtop');
   		$('.menuv_osinergmin ul').first().removeClass('close_ul').addClass('open_ul');
   	    $(this).parents().andSelf().removeClass('close_ul');
        $(this).parents().andSelf().addClass('open_ul').parent('li').has( "ul" ).removeClass('arrowtop').addClass('arrowbottom');
        $(this).parent().find('ul').first().removeClass('close_ul').addClass('open_ul');
		$(this).addClass('active');
     }   
    });






	var varSetIntervalSeleccion=setInterval(function() {
        	if($(".hovertable2 tr").length)
        	{
			$(".hovertable2 tr").each(function(){
				if($("> td", this).length == 2)
				{
					var texto = $("> td:eq(1)", this).html();
					if(texto.indexOf('*') > -1)
					{	
						texto = texto.split('*')[0] + "&nbsp;<span style='color:red'>*</span>";
						$("> td:eq(1)", this).html(texto);
					}
				}
			});
                	clearInterval(varSetIntervalSeleccion);
        	}
   	},500);

		/******************* onload ************************/	
		
		var varSetIntervalSocial=setInterval(function() {
        	if($("#foo_1").length)
        	{
                           
            	$("#foo_1").carouFredSel({
					responsive: true,
					auto: true,
					prev: '#prev_1',
					next: '#next_1',
					pagination	: false,
					scroll : { fx : "crossfade", duration: 1500 },
					items: {
						width: 400,
						//	height: '30%',	//	optionally resize item-height
						visible: {
						min: 1,
						max: 1
						}
					}
				});                           
				clearInterval(varSetIntervalSocial);
        	}
   		},500);
   			 
		var varSetIntervalSocial2=setInterval(function() {
                                                  
        	if($("#accordion").length)
        	{
            	$('#accordion').accordion({
					autoheight: false
				});                         
				clearInterval(varSetIntervalSocial2);
        	}
                    	 
   		},500);
   		
   		
   		var varSetIntervalSocial3=setInterval(function() {
                                                  
        	if($(".caja1").length)
            {
                           
            	$('.caja1 > ul > li:has(ul)').addClass("has-sub");
				$('.caja1 > ul > li.has-sub a').each(function(i) {
					$(this).addClass("sub-item" + (i+1));
				});
				$('.caja1 > ul > li.has-sub').find(".sub-item1").attr('href','#');
							   
				$('.caja1 > ul > li > a').click(function() {
					var checkElement = $(this).next();
							    
							    $('.caja1 li').removeClass('active');
							    $(this).closest('li').addClass('active');	
							    
							    
							    if((checkElement.is('ul')) && (checkElement.is(':visible'))) {
							      $(this).closest('li').removeClass('active');
							      checkElement.slideUp('normal');
							    }
							    
							    if((checkElement.is('ul')) && (!checkElement.is(':visible'))) {
							      $('.caja1 ul ul:visible').slideUp('normal');
							      checkElement.slideDown('normal');
							    }
							    
							    if (checkElement.is('ul')) {
							      return false;
							    } else {
							      return true;	
							    }		
					});                         
					clearInterval(varSetIntervalSocial3);
            }
   		},500);

		/*********************************************/	

		$( ".ms-core-listMenu-verticalBox" ).each(function(i) {
	        $(this).addClass("caja" + (i+1));
	    });
	    $( ".caja1" ).append( "<div class='head'></div>" );
	    $( ".caja1 .ms-core-listMenu-item" ).append( "<div class='bullet'></div>" );
		
	    $( ".ms-core-listMenu-horizontalBox li.static ul li" ).removeAttr("class");
		$( ".ms-core-listMenu-horizontalBox li.static" ).each(function(i) {
	        $(this).addClass("item" + (i+1));
	    });
	    
	    $( ".ms-core-listMenu-horizontalBox .static a span" ).removeClass( "additional-background" );
	    $( ".ms-core-listMenu-horizontalBox .static a" ).addClass( "navegacion" );
	    //$( ".ms-core-listMenu-horizontalBox .static ul.dynamic a" ).removeClass( "navegacion" );
	    $( ".ms-core-listMenu-horizontalBox .static ul.static a" ).removeClass( "navegacion" );
		$( ".ms-core-listMenu-horizontalBox .static .navegacion" ).each(function(i) {
	        $(this).addClass("item" + (i+1)).append( "<div class='ico'></div>" );
	    });
    
    	
	  var loc = window.location.href; // returns the full URL
	  loc=loc.toString().toLowerCase();
	  // Para mostrar iconos seg�n el escenario
	  if(/acerca_osinergmin/.test(loc)) {
		  var titulo = $.parseHTML("Informaci&oacute;n Institucional");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/institucional/.test(loc)) {
            var titulo = $.parseHTML("Institucional");
	    $( ".caja1 .head" ).html(titulo); 
	  }
	  if(/sistema_integrado_gestion/.test(loc)) {
	    $( ".caja1 .head" ).text( "SIG" );
	  }
	  if(/consejo_usuarios/.test(loc)) {
	    $( ".caja1 .head" ).text( "Consejo de Usuarios" );
	  }
	   if(/solucion-controversias/.test(loc)) {
            var titulo = $.parseHTML("Soluci&oacute;n de Controversias");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/estudios_economicos/.test(loc)) {
            var titulo = $.parseHTML("Pol&iacute;ticas y An&aacute;lisis Econ&oacute;mico");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/gart/.test(loc)) {
            var titulo = $.parseHTML("Regulaci&oacute;n Tarifaria");
	    $( ".caja1 .head" ).html(titulo);
	  }
          if(/stor/.test(loc)) {
            var titulo = $.parseHTML("Secretar&iacute;a T&eacute;cnica");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/que-es-jaru/.test(loc)) {
            var titulo = $.parseHTML("JARU");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/que-es-tastem/.test(loc)) {
            var titulo = $.parseHTML("TASTEM");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  
	  if(/publicaciones/.test(loc)) {
            var titulo = $.parseHTML("Publicaciones");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/eventos/.test(loc)) {
            var titulo = $.parseHTML("Eventos");
	    $( ".caja1 .head" ).html(titulo);
      }
	  if(/procesos-seleccion/.test(loc)) {
            var titulo = $.parseHTML("Concursos de Selecci&oacute;n");
	    $( ".caja1 .head" ).html(titulo);
	  }
		
	  if(/pre-publicacion-resoluciones/.test(loc)) {
            var titulo = $.parseHTML("Pre-Publicaciones");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/politicas/.test(loc)) {
            var titulo = $.parseHTML("Pol&iacute;ticas");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/sobre-administrador-fise/.test(loc)) {
            var titulo = $.parseHTML("Sobre el Administrador FISE");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/ceu/.test(loc)) {
            var titulo = $.parseHTML("CEU");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/aplicaciones-moviles/.test(loc)) {
            var titulo = $.parseHTML("Aplicaciones m&oacute;viles");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/oportunidades-laborales/.test(loc)) {
            var titulo = $.parseHTML("Oportunidades Laborales");
	    $( ".caja1 .head" ).html(titulo);
	  }
      if(/sistema-de-control-interno/.test(loc)) {
            var titulo = $.parseHTML("Sistema de Control Interno");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  
	  if(/analisis-de-impacto-regulatorio/.test(loc)) {
            var titulo = $.parseHTML("RIA");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  if(/cartas-servicio/.test(loc)) {
            var titulo = $.parseHTML("Cartas de Servicio");
	    $( ".caja1 .head" ).html(titulo);
	  }
	  

	 
    	//alert(ultimoval);
    	
    		
			var urlEscenario,urlCategoria ;
			var itemsUrl=window.location.pathname.split("/");
			if(itemsUrl.length>=2 && itemsUrl[1].toUpperCase() != "PAGINAS" && itemsUrl[1].toUpperCase() != "NOTICIAS" && itemsUrl[1].toUpperCase() != "EVENTOS" && itemsUrl[1].toUpperCase() != "OSINERGMIN_ORIENTA" && itemsUrl[1].toUpperCase() != "CENTRO_DE_BUSQUEDA")
			urlEscenario = itemsUrl[2];			 
			if(itemsUrl.length>=3 && itemsUrl[1].toUpperCase() != "PAGINAS" && itemsUrl[1].toUpperCase() != "NOTICIAS" && itemsUrl[1].toUpperCase() != "EVENTOS" && itemsUrl[1].toUpperCase() != "OSINERGMIN_ORIENTA" && itemsUrl[1].toUpperCase() != "CENTRO_DE_BUSQUEDA")
			urlCategoria = itemsUrl[3];
		    
		    if(urlEscenario)
			{	
				/*var link=$('.ms-core-listMenu-horizontalBox .static a.selected' ).attr('href');
				var arrayhref=link.split("/");
		    	var ultimoval=arrayhref[arrayhref.length-1];
				$('.ms-core-listMenu-horizontalBox .static a.selected' ).attr( 'id',ultimoval );
				
				$('.ms-core-listMenu-horizontalBox .static a.selected').each(function () {
			         var urlamigable = $(this).attr("id");	
			         if (urlamigable == urlEscenario ) 
			         {*/
						var submenu=$('.ms-core-listMenu-horizontalBox .static a.selected').parent().find( "ul") ;
						if(submenu.length != 0)
						{
						   	$(submenu).toggleClass( "visible" ).appendTo( ".list_carousel" );
					    	$( ".submenu" ).toggleClass( "visible" );
							$('.list_carousel ul').attr('id', 'foo_menu');             
						}
					  /*}
				  });*/
			     
			}	     
			if(urlCategoria)
		    {
		    	
		    	/*var clase2=$('.ms-core-listMenu-horizontalBox .static a.selected' ).attr('class');
		    	var inicio2=clase2.indexOf(' item');
		    	var item=clase2.substring(inicio2+1);
	    	
			    var link2=$('.ms-core-listMenu-horizontalBox li.static ul.static li a.selected' ).attr('href');
	       		
		    	var arrayhref2=link2.split("/");
		    	var ultimoval2=arrayhref2[arrayhref2.length-1];
	    		$('.ms-core-listMenu-horizontalBox li.static ul.static li a.selected' ).attr( 'id',ultimoval2 );*/
	    		
		    	//para agregar seleccionado a item padre
		    	var menuinicio= $('.ms-core-listMenu-horizontalBox li.static ul.static li a.selected').parent().parent().parent().find( "a.navegacion");
	 			$(menuinicio).addClass( "selected-menu" );
	 			
	 			
			     //Configuracion de la disposicion inicial del Menu
			     //$('.ms-core-listMenu-horizontalBox li.static ul.static li a.selected').each(function () {
			         //var urlamigable = $(this).attr("id");	
			         
			         //if (urlamigable == urlCategoria ) {
					   	var submenu= $('.ms-core-listMenu-horizontalBox li.static ul.static li a.selected').parent().parent();
					   	$(submenu).toggleClass( "visible" ).appendTo( ".list_carousel" );
			    		$( ".submenu" ).toggleClass( "visible" );
						$('.list_carousel ul').attr('id', 'foo_menu');             
			        // }
			         
			     //});
		     }
		     
	$('#foo_menu').carouFredSel({
		responsive: true,
		auto: false,
		prev: '#prev_menu',
		next: '#next_menu',
		pagination: "#pager_menu",
		width: '100%',
		scroll: 1,
		items: {
			width: 400,
		//	height: '30%',	//	optionally resize item-height
			visible: {
				min: 4,
				max: 4
			}
		}
	});
    
});
var a=0;
function ObtenerMesEvento()
{
	var months = new Array(12);
	months[0] = "Enero";
	months[1] = "Febrero";
	months[2] = "Marzo";
	months[3] = "Abril";
	months[4] = "Mayo";
	months[5] = "Junio";
	months[6] = "Julio";
	months[7] = "Agosto";
	months[8] = "Setiembre";
	months[9] = "Octubre";
	months[10] = "Noviembre";
	months[11] = "Diciembre";
	
	var Fecha=new Date();
	var Mes=Fecha.getMonth();
	return months[Mes].toString().toUpperCase();
}
function GenerarContador()
{
	a=a+1;
	return a;
}



		function abrir_dialog(src) {
		$( "#dialog" ).dialog({
		modal: true,
		width:980,
		height:450
		});
		//e.preventDefault();
		$('.class_iframe').attr('src', src);
		return false;
		}
		function abrir_dialog2(src) {
		$( "#dialog2" ).dialog({
		modal: true,
		width:600,
		height:450
		});
		//e.preventDefault();
		$('.class_iframe').attr('src', src);
		return false;
		}

var ValorItemID=0;
function AsignarValor(a)
{	
	ValorItemID=a;
}
function DevolverValorItem()
{	
	return ValorItemID;
}
function ObtenerPlanAnual()
{
  var requestUri ="/_api/search/query?querytext='69C9DB1F-0B94-4C79-A1E6-CBFAC0D25469'&selectproperties='Title,AnioOWSCHCS,ListItemID,FileExtension'&sortlist='int00:descending'&QueryTemplatePropertiesUrl='spfile://webroot/queryparametertemplate.xml'"

	$.ajax({
		 url:requestUri,
		 async: false,
		 type: "GET",
         headers: { "Accept": "application/json; odata=verbose" },
         success: function (data) {onRetornoPlanAnual(data)},
		 error: function(ts) { alert(ts.responseText); }
	});
}
function onRetornoPlanAnual(data)
{
	var TotalFilas= data.d.query.PrimaryQueryResult.RelevantResults.TotalRows;
	TotalFilas=TotalFilas-1;
	var results = data.d.query.PrimaryQueryResult.RelevantResults.Table.Rows.results;
	var item=[];

	//item.push("<select class='campo-desplegable' id='Anio'>");
	/*$.each(this.Cells.results,function(key,val)
	{item.push("<option value='"+val.Title+"'>"+val.Title+"</option>");

	})*/
 var AnioMemoria="";
 var Contador=0;
 
 $.each(results, function () {
 		Contador=Contador+1;
 		var Titulo="";
 		var Anio="";
 		var Url="";
 		var ID="";
 		var extension="";
        $.each(this.Cells.results, function () {
        	if(this.Key=="Title")
        	{
        		Titulo=this.Value;
			}
			if(this.Key=="AnioOWSCHCS")
        	{
     		     Anio=this.Value;
			}
			if(this.Key=="Path")
        	{
     		     Url=this.Value;
			}
			if(this.Key=="ListItemID")
        	{
     		     ID=this.Value;
			}
			if(this.Key=="FileExtension")
        	{
     		     extension=this.Value;
			}		

        });
        
			if(ID!=null)
			{
				if(AnioMemoria!=Anio && Contador!=1)
				{
					item.push("</ul>");
					item.push("</li>");	  
				}
				if(AnioMemoria!=Anio)
				{
					ObtenerTotalPlanAnualxAnio(Anio);
	  				item.push(" <li class='Collapsed'><div class='q1'>PAC - "+ Anio +" ("+TotalFilasAnio+")</div>");
	  				item.push("<ul>");
	  			}
	  			item.push("<li><div class="+extension+"></div><div class='doc'><a target='_blank' href='"+Url+"'>"+Titulo+"</a></div></li>");	
	  			if(Contador==TotalFilas+1)
	  			{
	  				item.push("</ul>");	 
	  				item.push("</li>"); 			
	  			}
	  			  			
  			}
  			AnioMemoria=Anio;
		 			

    });
	 
	 $("#TreeView").html(item.join(""));

}

function ObtenerTotalPlanAnualxAnio(Anio)
{
  var requestUri ="/_api/search/query?querytext='69C9DB1F-0B94-4C79-A1E6-CBFAC0D25469+AND+AnioOWSCHCS="+Anio+"'&selectproperties='Title,AnioOWSCHCS'&sortlist='int00:descending'&QueryTemplatePropertiesUrl='spfile://webroot/queryparametertemplate.xml'"

	$.ajax({
		 url:requestUri,
		 async: false,
		 type: "GET",
         headers: { "Accept": "application/json; odata=verbose" },
         success: function (data) {onTotalPlanAnualxAnio(data)},
		 error: function(ts) { alert(ts.responseText); }
	});
}
TotalFilasAnio=0;
function onTotalPlanAnualxAnio(data)
{
	TotalFilasAnio= data.d.query.PrimaryQueryResult.RelevantResults.TotalRows;
}

$(document).ready(function(){
		var urlactual=window.location.href;
		urlactual=urlactual.toLowerCase();
		if(urlactual.indexOf("plan_anual_adquisiciones_contrataciones") != -1)
		{
			Array.prototype.indexOf = IndexOf;

			ObtenerPlanAnual();
			
			
			var varSetIntervalSocial5=setInterval(function() {
        	if($("#TreeView").length)
        	{
                           
            	SetupTreeView("TreeView");              
				clearInterval(varSetIntervalSocial5);
        	}
   		},500);

			
		}
		
});
//Toggles between two classes for an element
function ToggleClass(element, firstClass, secondClass, event)
{
    event.cancelBubble = true;
    
    var classes = element.className.split(" ");
    var firstClassIndex = classes.indexOf(firstClass);
    var secondClassIndex = classes.indexOf(secondClass);
    
    if (firstClassIndex == -1 && secondClassIndex == -1)
    {
        classes[classes.length] = firstClass;
    }
    else if (firstClassIndex != -1)
    {
        classes[firstClassIndex] = secondClass;
    }
    else
    {
        classes[secondClassIndex] = firstClass;
    }
    
    element.className = classes.join(" ");
    
}
//Finds the index of an item in an array
function IndexOf(item)
{
    for (var i=0; i < this.length; i++)
    {        
        if (this[i] == item)
        {
            return i;
        }
    }
    
    return -1;
}
//The toggle event handler for each expandable/collapsable node
//- Note that this also exists to prevent any IE memory leaks 
//(due to circular references caused by this)
function ToggleNodeStateHandler(event)
{
    ToggleClass(this, "Collapsed", "Expanded", (event == null) ? window.event : event);
}
//Prevents the onclick event from bubbling up to parent elements
function PreventBubbleHandler(event)
{
    if (!event) event = window.event;
    event.cancelBubble = true;
}
//Adds the relevant onclick handlers for the nodes in the tree view
function SetupTreeView(elementId)
{
    var tree = document.getElementById(elementId);
    var treeElements = tree.getElementsByTagName("li");
    
    for (var i=0; i < treeElements.length; i++)
    {
        if (treeElements[i].getElementsByTagName("ul").length > 0)
        {
            treeElements[i].onclick = ToggleNodeStateHandler; 
        }
        else
        {
            treeElements[i].onclick = PreventBubbleHandler; 
        }
    }
}

// Para Inicio sesion
$(document).ready(function(){
   
   var varSetIntervalSesion=setInterval(function() {
   			
   			if($(".ms-signInLink").length)
   			{
				  var loc = window.location.href; // returns the full URL
				  loc=loc.toString().toLowerCase();
				  if(loc.indexOf("osinergmin.gob.pe") == -1){
				    $(".ms-signInLink").attr("style","display:block");
				    $(".contenido-uno").attr("style", "margin:0");
				  }
				  else {
				  $(".ms-signInLink").attr("style", "");
				  $(".contenido-uno").attr("style", "margin:0");
				  }
			      clearInterval(varSetIntervalSesion);
			}
    },500);
    
   var varSetIntervalPoo=setInterval(function() {
   			
   			if($(".phone").length)
   			{
				  var loc = window.location.href; // returns the full URL
				  loc=loc.toString().toLowerCase();
				  if(loc.indexOf("osinergmin.gob.pe") == -1){
				    $(".phone a").attr("onclick", "abrir_dialog2('http://portal/Paginas/servicio_telefonico.aspx')");
				  }
				  else {
				  $(".phone a").attr("onclick", "abrir_dialog2('http://portal.osinergmin.gob.pe/Paginas/servicio_telefonico.aspx')");
				  }
			      clearInterval(varSetIntervalPoo);
			}
    },500);

});
/*INICIO OPORTUNIDADES*/
var showCalendarOportunidades= function(numberElement){
	$("#itemOportunidad_" + numberElement).fadeIn("slow");
	return false;
}
var hideCalendarOportunidades= function(numberElement){
	$("#itemOportunidad_" + numberElement).fadeOut("slow");
	return false;
}
$(document).ready(function(){

	$("#dllEstadosConvocatoria").change(function(e){
		
		var estado= $("#dllEstadosConvocatoria").val();
        		$(".col-details-uno .ms-srch-sbLarge-fullWidth").val(estado);
        		$(".col-details-uno .ms-srch-sb-searchLink").click();

	});
    


   
});


/*FIN OPORTUNIDADES*/
