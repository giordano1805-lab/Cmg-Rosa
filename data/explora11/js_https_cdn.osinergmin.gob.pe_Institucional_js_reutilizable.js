$(document).ready(function(){
	var varSetIntervalxacc=setInterval(function() {
											  
		if($(".layout-acordeon").length)
		{
			$('.layout-acordeon ul').accordions();
			clearInterval(varSetIntervalxacc);
		}
	},500);
	var varSetIntervalxinfinito=setInterval(function() {
											  
		if($(".accordion-infinite").length)
		{
			$('.accordion-infinite .acordeon-over').each(function(i) {
			$(this).attr( "href", "#" + (i+1) );
			});
			
			$('.accordion-infinite ul').accordions();
			clearInterval(varSetIntervalxinfinito);
		}
	},500);
});